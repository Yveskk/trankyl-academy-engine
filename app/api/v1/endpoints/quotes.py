"""Demandes de devis : formulaire public (« Demander un devis ») et menu admin « Devis ».

- Visiteur non connecte : il saisit prenom, telephone et e-mail ; client connecte : ses coordonnees viennent de son compte.
- Chaque demande est enregistree puis signalee par e-mail a l'administration (ADMIN_EMAIL).
- L'administration repond depuis le panneau : la reponse part par e-mail au demandeur."""
import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.api.deps import bearer_scheme, current_country, current_lang, require_access
from app.core.rate_limit import limiter
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.client import Client
from app.models.quote import QuoteRequest
from app.services import quote_mail
from app.services.security import verification as vf
from app.services.countries import provider_in_country

router = APIRouter()

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class QuoteIn(BaseModel):
    vendor_id: int
    message: str = Field(min_length=3, max_length=2000)
    slot_label: str | None = Field(default=None, max_length=80)
    # Obligatoires seulement si le visiteur n'est pas connecte en tant que client.
    name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=255)


def _optional_client(credentials: HTTPAuthorizationCredentials | None, db: Session) -> Client | None:
    """Client connecte s'il y en a un ; sinon None (le formulaire public reste ouvert aux visiteurs)."""
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("role") != "client":
        return None
    client = db.get(Client, int(payload["sub"]))
    return client if client is not None and client.is_active else None


def _client_phone(c: Client) -> str | None:
    raw = (c.phone or "").strip()
    if not raw:
        return None
    if raw.startswith("+"):
        return raw
    return f"+{(c.country_code or '').lstrip('+')}{raw.lstrip('0')}" if c.country_code else raw


@router.post("", status_code=201)
@limiter.limit("10/hour")
def create_quote(
    request: Request, background: BackgroundTasks, payload: QuoteIn, lang: str = Depends(current_lang), country: str = Depends(current_country),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db),
):
    vendor = db.execute(text("SELECT vendor_name FROM vendors WHERE vendor_id=:v"), {"v": payload.vendor_id}).first()
    if vendor is None or not provider_in_country(db, payload.vendor_id, country):
        raise HTTPException(status_code=404, detail="Prestataire introuvable.")
    client = _optional_client(credentials, db)
    if client is not None:
        name, email, phone = " ".join((client.client_name or "").split()), (client.email or "").strip(), _client_phone(client)
    else:
        name, email = " ".join((payload.name or "").split()), (payload.email or "").strip()
        phone = vf.normalize_e164(payload.phone)
        if len(name) < 2:
            raise HTTPException(status_code=422, detail="Indiquez votre prénom.")
        if not EMAIL.match(email):
            raise HTTPException(status_code=422, detail="Adresse e-mail invalide.")
        if not phone:
            raise HTTPException(status_code=422, detail="Numéro de téléphone invalide.")
    q = QuoteRequest(
        country_code=country, vendor_id=payload.vendor_id, vendor_name=vendor[0], client_id=client.id if client else None, name=name, phone=phone, email=email,
        message=payload.message.strip(), slot_label=(payload.slot_label or "").replace("|", " ").strip() or None, lang="en" if lang == "en" else "fr", status="new",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    # E-mail a l'administration APRES la reponse : un echec d'envoi ne bloque jamais la demande.
    background.add_task(
        quote_mail.notify_admins_new_quote,
        {"id": q.id, "vendor_id": q.vendor_id, "vendor_name": q.vendor_name, "client_id": q.client_id, "name": q.name, "phone": q.phone, "email": q.email,
         "message": q.message, "slot_label": q.slot_label, "country_code": q.country_code},
    )
    return {"id": q.id, "status": q.status}


# ===================================================================== ADMINISTRATION : menu "Devis"
def _out(q: QuoteRequest) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {
        "id": q.id, "vendor_id": q.vendor_id, "vendor_name": q.vendor_name, "client_id": q.client_id, "name": q.name, "phone": q.phone, "email": q.email,
        "message": q.message, "slot_label": q.slot_label, "lang": q.lang, "status": q.status, "country": q.country_code, "created_at": iso(q.created_at),
        "reply_subject": q.reply_subject, "reply_message": q.reply_message, "replied_by": q.replied_by, "replied_at": iso(q.replied_at),
    }


@router.get("/admin")
def admin_list(status: str | None = None, q: str = "", page: int = 1, page_size: int = 20, admin=Depends(require_access("quotes", write="manage")), db: Session = Depends(get_db)):
    """Devis du pays courant : filtre par statut, recherche (nom, e-mail, telephone, prestataire, message), pagination, compteurs."""
    base = db.query(QuoteRequest).filter(QuoteRequest.country_code == admin.country)
    counts = {"all": base.count()}
    for st, n in db.query(QuoteRequest.status, func.count()).filter(QuoteRequest.country_code == admin.country).group_by(QuoteRequest.status).all():
        counts[st] = n
    counts.setdefault("new", 0)
    counts.setdefault("answered", 0)
    query = base
    if status in ("new", "answered"):
        query = query.filter(QuoteRequest.status == status)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(QuoteRequest.name.like(like), QuoteRequest.email.like(like), QuoteRequest.phone.like(like), QuoteRequest.vendor_name.like(like), QuoteRequest.message.like(like)))
    page_size = min(max(page_size, 5), 100)
    total = query.count()
    rows = query.order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size).all()
    return {"items": [_out(r) for r in rows], "total": total, "page": max(page, 1), "page_size": page_size, "counts": counts}


class ReplyIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=3, max_length=5000)


@router.post("/admin/{quote_id}/reply")
@limiter.limit("60/hour")
def admin_reply(request: Request, quote_id: int, payload: ReplyIn, admin=Depends(require_access("quotes", write="manage")), db: Session = Depends(get_db)):
    """Envoie la reponse par e-mail au demandeur ; elle n'est enregistree (statut « repondu ») que si l'e-mail est bien parti."""
    q = db.get(QuoteRequest, quote_id)
    if q is None or q.country_code != admin.country:
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    subject, html = quote_mail.render_reply(_out(q), payload.subject.strip(), payload.message.strip())
    try:
        quote_mail.deliver(q.email, subject, html, "quote_reply", strict=True)
    except Exception:  # noqa: BLE001 - MailError : le detail technique est journalise, pas renvoye
        raise HTTPException(status_code=502, detail="L'e-mail n'a pas pu être envoyé. Réessayez dans un instant.")
    q.status, q.reply_subject, q.reply_message = "answered", payload.subject.strip(), payload.message.strip()
    q.replied_by, q.replied_at = admin.email, datetime.utcnow()
    db.commit()
    return _out(q)
