"""Moteur de matching + messagerie + gestion apprenants (admin)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin, get_current_apprenant, get_optional_admin
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.certification import Certification
from app.models.curriculum import Module
from app.models.matching import MatchingRequest, Match, Message
from app.models.chat_history import ChatSession, ChatMessageRecord
from app.models.progress import Enrollment
from app.models.taxonomy import Competence, Niveau, Metier
from app.models.trust import TrustScore
from app.models.user import AdminUser, Apprenant
from app.schemas.matching import (
    ApprenantDetailOut,
    ApprenantOut,
    ChatMessageOut,
    ChatSessionDetailOut,
    ChatSessionOut,
    ConversationOut,
    MatchingRequestCreate,
    MatchingRequestOut,
    MatchOut,
    MessageCreate,
    MessageOut,
    PrestataireMatchOut,
    TrustScoreOut,
    VerificationUpdate,
)
from app.services.ai_matching import chat_with_ai
from app.services.matching_score import compute_match_score
from app.services.trust_score import compute_trust_score, is_matching_eligible

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


# ====================================================================
# MOTEUR DE MATCHING
# ====================================================================

@router.post("/requests", response_model=MatchingRequestOut, status_code=201)
def create_matching_request(
    payload: MatchingRequestCreate,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    """Le client crée une demande de recherche de prestataire pour un metier."""
    metier = db.query(Metier).filter(Metier.code == payload.metier_code).first()
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    req = MatchingRequest(client_id=current.id, metier_code=payload.metier_code, description=payload.description)
    db.add(req)
    db.commit()
    db.refresh(req)

    # Lancer le matching automatiquement
    _compute_matches(db, req)
    return req


@router.get("/requests", response_model=list[MatchingRequestOut])
def my_requests(
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    return db.query(MatchingRequest).filter(MatchingRequest.client_id == current.id).order_by(MatchingRequest.created_at.desc()).all()


@router.get("/requests/{request_id}/matches", response_model=list[MatchOut])
def get_matches(
    request_id: int,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    req = db.get(MatchingRequest, request_id)
    if not req or req.client_id != current.id:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    return db.query(Match).filter(Match.request_id == request_id).order_by(Match.score.desc()).all()


@router.get("/prestataires", response_model=list[PrestataireMatchOut])
def search_prestataires(
    metier_code: str | None = None,
    db: Session = Depends(get_db),
):
    """Recherche publique de prestataires certifies (pour le moteur de
    matching). Blocage automatique : un apprenant non verifie, ou sans score
    de confiance calcule, ou sous le seuil, n'apparait jamais ici — meme
    s'il a des certifications. Si `metier_code` est fourni, chaque candidat
    recoit un score de matching pondere et explicable (voir
    app.services.matching_score), et la liste est triee par score decroissant."""
    certified = db.query(Certification).all()

    prestataires_map: dict[int, dict] = {}
    for cert in certified:
        if metier_code:
            niveau = db.get(Niveau, cert.niveau_id)
            if not niveau:
                continue
            metier = db.get(Metier, niveau.metier_id)
            if not metier or metier.code != metier_code:
                continue

        if cert.apprenant_id not in prestataires_map:
            apprenant = db.get(Apprenant, cert.apprenant_id)
            if not apprenant:
                continue
            trust = db.query(TrustScore).filter(TrustScore.apprenant_id == apprenant.id).first()
            if not is_matching_eligible(apprenant, trust):
                continue

            entry: dict = {
                "id": apprenant.id,
                "firstname": apprenant.firstname,
                "lastname": apprenant.lastname,
                "email": apprenant.email,
                "certifications": [],
                "score": 0,
                "trust_score": trust.score_pct,
            }
            if metier_code:
                match = compute_match_score(db, apprenant, metier_code, trust)
                entry["match_score"] = match["score"]
                entry["match_breakdown"] = match["breakdown"]
            prestataires_map[apprenant.id] = entry

        if cert.apprenant_id in prestataires_map:
            prestataires_map[cert.apprenant_id]["certifications"].append(cert.code)

    results = list(prestataires_map.values())
    if metier_code:
        results.sort(key=lambda r: r["match_score"] or 0, reverse=True)
    return results


@router.get("/prestataires/{apprenant_id}/trust-score", response_model=TrustScoreOut)
@limiter.limit("30/minute")
def get_trust_score(
    request: Request,
    apprenant_id: int,
    recompute: bool = False,
    db: Session = Depends(get_db),
    admin: AdminUser | None = Depends(get_optional_admin),
):
    """Score de confiance d'un apprenant (public, transparent — pas de boite
    noire). Retourne le score mis en cache s'il existe deja. `?recompute=true`
    force un recalcul reserve aux admins : ce recalcul appelle Gemini (cout
    reel) et ecrit en base, donc pas question de le laisser declenchable en
    boucle par n'importe qui en GET public."""
    apprenant = db.get(Apprenant, apprenant_id)
    if not apprenant:
        raise HTTPException(status_code=404, detail="Apprenant introuvable")

    if recompute and admin is None:
        raise HTTPException(status_code=403, detail="Recalcul reserve aux administrateurs")

    trust = None if recompute else db.query(TrustScore).filter(TrustScore.apprenant_id == apprenant_id).first()
    if trust is None:
        trust = compute_trust_score(db, apprenant)

    return TrustScoreOut(
        apprenant_id=trust.apprenant_id,
        score_pct=trust.score_pct,
        rules_score=trust.rules_score,
        rules_breakdown=json.loads(trust.rules_breakdown_json),
        llm_score=trust.llm_score,
        justification=trust.justification,
        computed_at=trust.computed_at,
    )


@router.patch(
    "/admin/apprenants/{apprenant_id}/verification",
    response_model=TrustScoreOut,
    dependencies=[Depends(get_current_admin)],
)
def update_verification(
    apprenant_id: int,
    payload: VerificationUpdate,
    db: Session = Depends(get_db),
):
    """Verification manuelle d'un apprenant par un admin (identite / serieux)
    et/ou mise a jour de ses references. Le score de confiance est
    recalcule immediatement pour que l'effet du blocage automatique soit
    demontrable en direct (verifie -> apparait dans le matching / non
    verifie -> disparait)."""
    apprenant = db.get(Apprenant, apprenant_id)
    if not apprenant:
        raise HTTPException(status_code=404, detail="Apprenant introuvable")

    if payload.is_verified is not None:
        apprenant.is_verified = payload.is_verified
        apprenant.verified_at = func.now() if payload.is_verified else None
    if payload.reference_notes is not None:
        apprenant.reference_notes = payload.reference_notes
    db.commit()
    db.refresh(apprenant)

    trust = compute_trust_score(db, apprenant)
    return TrustScoreOut(
        apprenant_id=trust.apprenant_id,
        score_pct=trust.score_pct,
        rules_score=trust.rules_score,
        rules_breakdown=json.loads(trust.rules_breakdown_json),
        llm_score=trust.llm_score,
        justification=trust.justification,
        computed_at=trust.computed_at,
    )


# ====================================================================
# SITA — ASSISTANT IA DE MATCHING
# ====================================================================

@router.post("/chat")
@limiter.limit("20/minute")
def chat(
    request: Request,
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    """Chat intelligent avec SITA (Gemini) — matching IA base sur les donnees DB."""
    try:
        response = chat_with_ai(payload.message, db, payload.history)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur SITA: {str(e)}")


@router.post("/chat/sessions", response_model=ChatSessionOut, status_code=201)
def create_chat_session(
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    session = ChatSession(user_id=current.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
def list_chat_sessions(
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    return db.query(ChatSession).filter(ChatSession.user_id == current.id).order_by(ChatSession.updated_at.desc()).all()


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetailOut)
def get_chat_session(
    session_id: int,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current.id:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return session


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatMessageOut, status_code=201)
@limiter.limit("20/minute")
def send_chat_message(
    request: Request,
    session_id: int,
    payload: ChatRequest,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    """Envoie un message dans une session et retourne la reponse IA avec boutons."""
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current.id:
        raise HTTPException(status_code=404, detail="Session introuvable")

    # Sauvegarder le message utilisateur
    user_msg = ChatMessageRecord(session_id=session_id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    # Recuperer l'historique pour le contexte
    history_records = (
        db.query(ChatMessageRecord)
        .filter(ChatMessageRecord.session_id == session_id)
        .order_by(ChatMessageRecord.created_at.asc())
        .all()
    )
    history = [{"role": r.role, "content": r.content} for r in history_records]

    # Appel IA
    try:
        response = chat_with_ai(payload.message, db, history[:-1])
    except Exception as e:
        response = f"❌ Erreur: {str(e)}"

    # Sauvegarder la reponse
    assistant_msg = ChatMessageRecord(session_id=session_id, role="assistant", content=response)
    db.add(assistant_msg)

    # Mettre a jour le titre de la session (premiers mots du 1er message)
    if len(history_records) <= 1:
        session.title = payload.message[:80]

    session.updated_at = func.now()
    db.commit()
    db.refresh(assistant_msg)

    return assistant_msg


@router.delete("/chat/sessions/{session_id}", status_code=204)
def delete_chat_session(
    session_id: int,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current.id:
        raise HTTPException(status_code=404, detail="Session introuvable")
    db.delete(session)
    db.commit()


def _compute_matches(db: Session, request: MatchingRequest) -> None:
    """Algorithme de matching : calcule un score 0-100 pour chaque prestataire certifie."""
    # Trouver les certifications pertinentes pour le metier
    niveaux = (
        db.query(Niveau)
        .join(Metier)
        .filter(Metier.code == request.metier_code)
        .all()
    )
    niveau_ids = {n.id for n in niveaux}
    if not niveau_ids:
        return

    # Trouver les apprenants certifies pour ce metier
    certifie = (
        db.query(Certification)
        .filter(Certification.niveau_id.in_(niveau_ids))
        .all()
    )

    prestataire_scores: dict[int, list[str]] = {}
    for c in certifie:
        if c.apprenant_id not in prestataire_scores:
            prestataire_scores[c.apprenant_id] = []
        prestataire_scores[c.apprenant_id].append(c.code)

    # Calculer le score pour chaque prestataire
    total_niveaux = len(niveau_ids)
    for apprenant_id, cert_codes in prestataire_scores.items():
        # Score base sur le % de niveaux couverts
        niveaux_couverts = len(set(cert_codes))
        score = round((niveaux_couverts / total_niveaux) * 100) if total_niveaux > 0 else 0

        match = Match(request_id=request.id, prestataire_id=apprenant_id, score=score)
        db.add(match)

    db.commit()


# ====================================================================
# MESSAGERIE
# ====================================================================

@router.post("/messages", response_model=MessageOut, status_code=201)
def send_message(
    payload: MessageCreate,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    receiver = db.get(Apprenant, payload.receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="Destinataire introuvable")
    msg = Message(
        sender_id=current.id,
        receiver_id=payload.receiver_id,
        match_id=payload.match_id,
        content=payload.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/messages/conversations", response_model=list[ConversationOut])
def my_conversations(
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    """Liste des conversations de l'utilisateur connecte."""
    # Trouver tous les IDs d'interlocuteurs
    sent = db.query(Message.receiver_id).filter(Message.sender_id == current.id).distinct().all()
    received = db.query(Message.sender_id).filter(Message.receiver_id == current.id).distinct().all()
    other_ids = {r[0] for r in sent} | {r[0] for r in received}

    conversations = []
    for other_id in other_ids:
        other = db.get(Apprenant, other_id)
        if not other:
            continue
        last_msg = (
            db.query(Message)
            .filter(
                ((Message.sender_id == current.id) & (Message.receiver_id == other_id))
                | ((Message.sender_id == other_id) & (Message.receiver_id == current.id))
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        unread = (
            db.query(func.count(Message.id))
            .filter(Message.sender_id == other_id, Message.receiver_id == current.id, Message.read == False)
            .scalar()
        )
        if last_msg:
            conversations.append(ConversationOut(
                other_user_id=other_id,
                other_user_name=f"{other.firstname} {other.lastname}",
                last_message=last_msg.content[:100],
                last_message_at=last_msg.created_at,
                unread_count=unread,
            ))
    conversations.sort(key=lambda c: c.last_message_at, reverse=True)
    return conversations


@router.get("/messages/{user_id}", response_model=list[MessageOut])
def get_messages(
    user_id: int,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    """Recuperer l'historique des messages avec un utilisateur."""
    messages = (
        db.query(Message)
        .filter(
            ((Message.sender_id == current.id) & (Message.receiver_id == user_id))
            | ((Message.sender_id == user_id) & (Message.receiver_id == current.id))
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    # Marquer comme lus
    for m in messages:
        if m.sender_id == user_id and not m.read:
            m.read = True
    db.commit()
    return messages


@router.get("/messages/unread/count")
def unread_count(
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    count = (
        db.query(func.count(Message.id))
        .filter(Message.receiver_id == current.id, Message.read == False)
        .scalar()
    )
    return {"count": count}


# ====================================================================
# ADMIN : GESTION DES APPRENANTS
# ====================================================================

@router.get("/admin/apprenants", response_model=list[ApprenantDetailOut], dependencies=[Depends(get_current_admin)])
def list_apprenants(db: Session = Depends(get_db)):
    """Liste tous les apprenants avec leurs certifications et progressions."""
    apprenants = db.query(Apprenant).order_by(Apprenant.created_at.desc()).all()
    result = []
    for a in apprenants:
        certs = db.query(Certification).filter(Certification.apprenant_id == a.id).all()
        enrollment_count = db.query(func.count(Enrollment.id)).filter(Enrollment.apprenant_id == a.id).scalar()
        completed_count = (
            db.query(func.count(Enrollment.id))
            .filter(Enrollment.apprenant_id == a.id, Enrollment.statut == "termine")
            .scalar()
        )
        trust = db.query(TrustScore).filter(TrustScore.apprenant_id == a.id).first()
        result.append(ApprenantDetailOut(
            id=a.id,
            firstname=a.firstname,
            lastname=a.lastname,
            email=a.email,
            phone=a.phone,
            created_at=a.created_at,
            certifications=[c.code for c in certs],
            enrollment_count=enrollment_count,
            completed_count=completed_count,
            is_verified=a.is_verified,
            trust_score=trust.score_pct if trust else None,
        ))
    return result
