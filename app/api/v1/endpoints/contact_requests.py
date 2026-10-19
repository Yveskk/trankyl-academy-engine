"""Mise en relation client <-> prestataire, moderee par l'admin :
1. Le client demande a contacter un prestataire (POST /contact-requests).
2. L'admin approuve ou rejette (PATCH /contact-requests/{id}/review).
3. Une fois approuvee, les deux parties peuvent echanger des messages dans
   ce fil (GET/POST /contact-requests/{id}/messages)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy import text
from app.services.countries import provider_in_country as vendor_in_country, provider_offer_clause as vendor_country_clause
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_client, get_current_client_or_apprenant, require_access
from app.db.session import get_db
from app.models.certification import Certification
from app.models.client import Client
from app.models.contact_request import ContactMessage, ContactRequest
from app.models.trust import TrustScore
from app.models.user import Apprenant
from app.schemas.contact_request import (
    ContactMessageCreate,
    ContactMessageOut,
    ContactRequestAdminOut,
    ContactRequestClientOut,
    ContactRequestCreate,
    ContactRequestPrestataireOut,
    ContactRequestReview,
)

router = APIRouter()


@router.post("", response_model=ContactRequestClientOut, status_code=201)
def create_contact_request(
    payload: ContactRequestCreate,
    current: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    prestataire = db.get(Apprenant, payload.prestataire_id)
    if not prestataire:
        raise HTTPException(status_code=404, detail="Prestataire introuvable")

    existing = (
        db.query(ContactRequest)
        .filter(ContactRequest.client_id == current.id, ContactRequest.prestataire_id == payload.prestataire_id)
        .first()
    )
    if existing:
        # Idempotent : on ne recree pas de demande en double, on renvoie
        # simplement l'etat actuel (pending/approuvee/rejetee).
        return ContactRequestClientOut(
            **{c: getattr(existing, c) for c in ("id", "client_id", "prestataire_id", "initial_message", "status", "created_at", "reviewed_at")},
            prestataire_nom=f"{prestataire.firstname} {prestataire.lastname}",
        )

    req = ContactRequest(client_id=current.id, prestataire_id=payload.prestataire_id, initial_message=payload.message)
    db.add(req)
    db.commit()
    db.refresh(req)
    return ContactRequestClientOut(
        id=req.id,
        client_id=req.client_id,
        prestataire_id=req.prestataire_id,
        initial_message=req.initial_message,
        status=req.status,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
        prestataire_nom=f"{prestataire.firstname} {prestataire.lastname}",
    )


def _unread_and_last(req: ContactRequest, viewer_role: str) -> dict:
    other_role = "prestataire" if viewer_role == "client" else "client"
    unread = sum(1 for m in req.messages if m.sender_role == other_role and not m.read)
    last = req.messages[-1] if req.messages else None
    return {
        "unread_count": unread,
        "last_message": last.content[:100] if last else None,
        "last_message_at": last.created_at if last else None,
    }


@router.get("/me/client", response_model=list[ContactRequestClientOut])
def my_contact_requests_as_client(
    current: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ContactRequest)
        .options(joinedload(ContactRequest.prestataire), joinedload(ContactRequest.messages))
        .filter(ContactRequest.client_id == current.id)
        .order_by(ContactRequest.created_at.desc())
        .all()
    )
    # Le prestataire peut avoir ete supprime du marketplace Trankyl depuis
    # (compte ferme) : on ignore ces demandes orphelines plutot que de
    # planter l'affichage.
    return [
        ContactRequestClientOut(
            id=r.id,
            client_id=r.client_id,
            prestataire_id=r.prestataire_id,
            initial_message=r.initial_message,
            status=r.status,
            created_at=r.created_at,
            reviewed_at=r.reviewed_at,
            prestataire_nom=f"{r.prestataire.firstname} {r.prestataire.lastname}",
            **_unread_and_last(r, "client"),
        )
        for r in rows
        if r.prestataire is not None
    ]


@router.get("/me/prestataire", response_model=list[ContactRequestPrestataireOut])
def my_contact_requests_as_prestataire(
    current: tuple[str, int] = Depends(get_current_client_or_apprenant),
    db: Session = Depends(get_db),
):
    role, user_id = current
    if role != "apprenant":
        raise HTTPException(status_code=403, detail="Reserve aux prestataires (apprenants)")
    rows = (
        db.query(ContactRequest)
        .options(joinedload(ContactRequest.client), joinedload(ContactRequest.messages))
        .filter(ContactRequest.prestataire_id == user_id)
        .order_by(ContactRequest.created_at.desc())
        .all()
    )
    # Le client peut avoir ete supprime du marketplace Trankyl depuis
    # (compte ferme) : on ignore ces demandes orphelines plutot que de
    # planter l'affichage.
    return [
        ContactRequestPrestataireOut(
            id=r.id,
            client_id=r.client_id,
            prestataire_id=r.prestataire_id,
            initial_message=r.initial_message,
            status=r.status,
            created_at=r.created_at,
            reviewed_at=r.reviewed_at,
            client_nom=f"{r.client.firstname} {r.client.lastname}",
            **_unread_and_last(r, "prestataire"),
        )
        for r in rows
        if r.client is not None
    ]


def _build_admin_out(db: Session, req: ContactRequest) -> ContactRequestAdminOut:
    """Assemble la vue admin d'une demande avec tout ce qui aide a la
    modération : coordonnées completes des deux parties, statut de
    verification et score de confiance du prestataire, ses certifications,
    l'historique de demandes du client (pour reperer un usage abusif), et
    l'activite du fil de discussion une fois approuve."""
    client_total_requests = db.query(ContactRequest).filter(ContactRequest.client_id == req.client_id).count()

    trust = db.query(TrustScore).filter(TrustScore.apprenant_id == req.prestataire_id).first()
    certifications = [
        c.code for c in db.query(Certification).filter(Certification.apprenant_id == req.prestataire_id).all()
    ]

    message_count = len(req.messages)
    last_message_at = req.messages[-1].created_at if req.messages else None

    return ContactRequestAdminOut(
        id=req.id,
        client_id=req.client_id,
        prestataire_id=req.prestataire_id,
        initial_message=req.initial_message,
        status=req.status,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
        client_nom=f"{req.client.firstname} {req.client.lastname}",
        client_email=req.client.email,
        client_phone=req.client.phone,
        client_created_at=req.client.created_at,
        client_total_requests=client_total_requests,
        prestataire_nom=f"{req.prestataire.firstname} {req.prestataire.lastname}",
        prestataire_email=req.prestataire.email,
        prestataire_phone=req.prestataire.phone,
        prestataire_is_verified=req.prestataire.is_verified,
        prestataire_trust_score=trust.score_pct if trust else None,
        prestataire_certifications=certifications,
        prestataire_created_at=req.prestataire.created_at,
        message_count=message_count,
        last_message_at=last_message_at,
    )


@router.get("/admin", response_model=list[ContactRequestAdminOut])
def admin_list_contact_requests(admin=Depends(require_access("contacts")), db: Session = Depends(get_db)):
    clause, cparams = vendor_country_clause(db, admin.country, "v")
    rows = (
        db.query(ContactRequest)
        .filter(text(f"academy_contact_requests.vendor_id IN (SELECT v.vendor_id FROM vendors v WHERE {clause})").bindparams(**cparams))
        .options(
            joinedload(ContactRequest.client),
            joinedload(ContactRequest.prestataire),
            joinedload(ContactRequest.messages),
        )
        .order_by(ContactRequest.created_at.desc())
        .all()
    )
    # Client ou prestataire peut avoir ete supprime du marketplace Trankyl
    # depuis (compte ferme) : on ignore ces demandes orphelines plutot que
    # de planter l'affichage admin.
    return [_build_admin_out(db, r) for r in rows if r.client is not None and r.prestataire is not None]


@router.patch("/{request_id}/review", response_model=ContactRequestAdminOut)
def review_contact_request(request_id: int, payload: ContactRequestReview, admin=Depends(require_access("contacts")), db: Session = Depends(get_db)):
    req = db.get(ContactRequest, request_id)
    if not req or not vendor_in_country(db, req.prestataire_id, admin.country):
        raise HTTPException(status_code=404, detail="Demande introuvable")
    req.status = payload.status
    req.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return _build_admin_out(db, req)


@router.get("/unread/count")
def unread_contact_message_count(
    current: tuple[str, int] = Depends(get_current_client_or_apprenant),
    db: Session = Depends(get_db),
):
    """Nombre total de messages non lus, tous fils de discussion approuves
    confondus, pour le client ou le prestataire connecte. Alimente le badge
    de notification dans la barre de navigation."""
    role, user_id = current
    filter_col = ContactRequest.client_id if role == "client" else ContactRequest.prestataire_id
    other_role = "prestataire" if role == "client" else "client"
    count = (
        db.query(func.count(ContactMessage.id))
        .join(ContactRequest, ContactMessage.contact_request_id == ContactRequest.id)
        .filter(filter_col == user_id, ContactMessage.sender_role == other_role, ContactMessage.read.is_(False))
        .scalar()
    )
    return {"count": count}


def _get_authorized_request(db: Session, request_id: int, role: str, user_id: int) -> ContactRequest:
    req = db.get(ContactRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    is_party = (role == "client" and req.client_id == user_id) or (role == "apprenant" and req.prestataire_id == user_id)
    if not is_party:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    return req


@router.get("/{request_id}/messages", response_model=list[ContactMessageOut])
def get_contact_messages(
    request_id: int,
    current: tuple[str, int] = Depends(get_current_client_or_apprenant),
    db: Session = Depends(get_db),
):
    role, user_id = current
    req = _get_authorized_request(db, request_id, role, user_id)
    if req.status != "approved":
        raise HTTPException(status_code=403, detail="Cette demande n'est pas encore approuvee par l'admin")

    # Marquer comme lus les messages envoyes par l'autre partie
    other_role = "prestataire" if role == "client" else "client"
    for m in req.messages:
        if m.sender_role == other_role and not m.read:
            m.read = True
    db.commit()

    return req.messages


@router.post("/{request_id}/messages", response_model=ContactMessageOut, status_code=201)
def send_contact_message(
    request_id: int,
    payload: ContactMessageCreate,
    current: tuple[str, int] = Depends(get_current_client_or_apprenant),
    db: Session = Depends(get_db),
):
    role, user_id = current
    req = _get_authorized_request(db, request_id, role, user_id)
    if req.status != "approved":
        raise HTTPException(status_code=403, detail="Cette demande n'est pas encore approuvee par l'admin")

    sender_role = "client" if role == "client" else "prestataire"
    msg = ContactMessage(contact_request_id=request_id, sender_role=sender_role, content=payload.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg
