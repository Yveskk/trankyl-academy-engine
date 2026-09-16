"""Moteur de matching + messagerie + gestion apprenants (admin)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin, get_current_apprenant
from app.db.session import get_db
from app.models.certification import Certification
from app.models.curriculum import Module
from app.models.matching import MatchingRequest, Match, Message
from app.models.chat_history import ChatSession, ChatMessageRecord
from app.models.progress import Enrollment
from app.models.taxonomy import Competence, Niveau, Metier
from app.models.user import Apprenant
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
)
from app.services.ai_matching import chat_with_ai

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


@router.get("/prestataires")
def search_prestataires(
    metier_code: str | None = None,
    db: Session = Depends(get_db),
):
    """Recherche publique de prestataires certifies (pour le moteur de matching)."""
    # Trouver tous les apprenants qui ont au moins une certification
    certified = (
        db.query(Certification)
        .all()
    )

    # Grouper par apprenant
    prestataires_map: dict[int, dict] = {}
    for cert in certified:
        # Verifier que la certification correspond au metier demande
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
            prestataires_map[cert.apprenant_id] = {
                "id": apprenant.id,
                "firstname": apprenant.firstname,
                "lastname": apprenant.lastname,
                "certifications": [],
            }
        prestataires_map[cert.apprenant_id]["certifications"].append(cert.code)

    return list(prestataires_map.values())


# ====================================================================
# ASSISTANT IA — CHAT DE MATCHING
# ====================================================================

@router.post("/chat")
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    """Chat intelligent avec Claude — matching IA base sur les donnees DB."""
    try:
        response = chat_with_ai(payload.message, db, payload.history)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur assistant IA: {str(e)}")


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
def send_chat_message(
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
        ))
    return result
