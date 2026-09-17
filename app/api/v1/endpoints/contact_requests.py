"""Mise en relation client <-> prestataire, moderee par l'admin :
1. Le client demande a contacter un prestataire (POST /contact-requests).
2. L'admin approuve ou rejette (PATCH /contact-requests/{id}/review).
3. Une fois approuvee, les deux parties peuvent echanger des messages dans
   ce fil (GET/POST /contact-requests/{id}/messages)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin, get_current_client, get_current_client_or_apprenant
from app.db.session import get_db
from app.models.client import Client
from app.models.contact_request import ContactMessage, ContactRequest
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
    ]


@router.get("/admin", response_model=list[ContactRequestAdminOut], dependencies=[Depends(get_current_admin)])
def admin_list_contact_requests(db: Session = Depends(get_db)):
    rows = (
        db.query(ContactRequest)
        .options(joinedload(ContactRequest.client), joinedload(ContactRequest.prestataire))
        .order_by(ContactRequest.created_at.desc())
        .all()
    )
    return [
        ContactRequestAdminOut(
            id=r.id,
            client_id=r.client_id,
            prestataire_id=r.prestataire_id,
            initial_message=r.initial_message,
            status=r.status,
            created_at=r.created_at,
            reviewed_at=r.reviewed_at,
            client_nom=f"{r.client.firstname} {r.client.lastname}",
            client_email=r.client.email,
            prestataire_nom=f"{r.prestataire.firstname} {r.prestataire.lastname}",
            prestataire_email=r.prestataire.email,
        )
        for r in rows
    ]


@router.patch(
    "/{request_id}/review", response_model=ContactRequestAdminOut, dependencies=[Depends(get_current_admin)]
)
def review_contact_request(request_id: int, payload: ContactRequestReview, db: Session = Depends(get_db)):
    req = db.get(ContactRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    req.status = payload.status
    req.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
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
        prestataire_nom=f"{req.prestataire.firstname} {req.prestataire.lastname}",
        prestataire_email=req.prestataire.email,
    )


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
