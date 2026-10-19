"""Espace prestataire — travail au quotidien : demandes (reservations), devis, agenda, paiements, avis, profil public.

Tout est limite aux donnees DU prestataire connecte. Ce qu'il modifie ici (profil public, realisations, services affiches,
disponibilites) est exactement ce que les clients voient dans l'annuaire et sur sa fiche."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_apprenant
from app.api.v1.endpoints.directory import clear_directory_cache
from app.api.v1.endpoints.provider_space import get_provider
from app.api.v1.endpoints.quotes import _out as quote_out
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.provider import ProviderAvailability, ProviderMedia, ProviderProfile
from app.models.quote import QuoteRequest
from app.models.review import Review
from app.models.user import Apprenant
from app.services import enrollment_files as ef
from app.services import quote_mail
from app.services.home import invalidate_home_cache
from app.services.image_upload import ImageUploadError, upload_image
from app.services.security import accounts as sec

router = APIRouter()
_STATUS = {None: "pending", "0": "pending", "1": "pending", "2": "completed", "3": "cancelled", "4": "cancelled"}
STATUS_SQL = {
    "pending": "(b.bk_service_status IS NULL OR b.bk_service_status IN ('0','1'))",
    "completed": "b.bk_service_status = '2'",
    "cancelled": "b.bk_service_status IN ('3','4')",
}


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso(d) -> str | None:
    return d.isoformat() if d else None


# --------------------------------------------------------------------------- demandes (reservations)
def _row(r) -> dict:
    return {
        "id": r["bk_id"], "ref": r["bk_unique_id"], "status": _STATUS.get(r["bk_service_status"], "pending"), "date": _iso(r["bk_date"]), "time": r["bk_time"],
        "service": r["s_title"], "qty": r["bk_qty"], "client_name": r["bk_client_name"], "client_phone": r["bk_client_phone"], "address": r["bk_address"],
        "info": r["bk_additional_info"], "map_link": r["bk_link_geolocation"], "total": _num(r["bk_amount_remaining"]) or _num(r["bk_total_amount"]),
        "payment_method": r["bk_payment_method"], "paid": str(r["bk_payment_status"]) == "1", "created_at": _iso(r["bk_created_at"]), "cancellation_reason": r["bk_cancellation_reason"],
    }


_FROM = "FROM bookings b LEFT JOIN services s ON s.s_id=b.bk_service_id"


@router.get("/requests")
def my_requests(status: str | None = None, q: str = "", page: int = 1, page_size: int = 20, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    db.rollback()
    where, p = ["b.bk_vendor_id=:v"], {"v": provider.id}
    if q.strip():
        where.append("(b.bk_unique_id LIKE :q OR b.bk_client_name LIKE :q OR b.bk_client_phone LIKE :q OR s.s_title LIKE :q)")
        p["q"] = f"%{q.strip()}%"
    base = " AND ".join(where)
    counts = {k: db.execute(text(f"SELECT COUNT(*) {_FROM} WHERE {base} AND {c}"), p).scalar() or 0 for k, c in STATUS_SQL.items()}
    counts["all"] = sum(counts.values())
    shown = base + (f" AND {STATUS_SQL[status]}" if status in STATUS_SQL else "")
    page, page_size = max(1, page), min(max(1, page_size), 100)
    rows = db.execute(
        text(f"SELECT b.*, s.s_title {_FROM} WHERE {shown} ORDER BY b.bk_created_at DESC, b.bk_id DESC LIMIT :l OFFSET :o"), {**p, "l": page_size, "o": (page - 1) * page_size}
    ).mappings().all()
    return {"total": counts[status] if status in STATUS_SQL else counts["all"], "page": page, "page_size": page_size, "counts": counts, "items": [_row(r) for r in rows]}


class StatusIn(BaseModel):
    status: str = Field(pattern="^(completed|cancelled)$")
    reason: str | None = Field(default=None, max_length=300)


@router.post("/requests/{booking_id}/status")
@limiter.limit("60/minute")
def set_request_status(request: Request, booking_id: int, payload: StatusIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Le prestataire marque SA mission terminee ou l'annule (seulement tant qu'elle est en attente)."""
    db.rollback()
    row = db.execute(text("SELECT bk_service_status FROM bookings WHERE bk_id=:i AND bk_vendor_id=:v"), {"i": booking_id, "v": provider.id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    if _STATUS.get(row[0], "pending") != "pending":
        raise HTTPException(status_code=409, detail="Cette demande n'est plus en attente.")
    if payload.status == "completed":
        db.execute(text("UPDATE bookings SET bk_service_status='2' WHERE bk_id=:i"), {"i": booking_id})
        db.execute(text("UPDATE vendors SET vendor_jobs_count=COALESCE(vendor_jobs_count,0)+1 WHERE vendor_id=:v"), {"v": provider.id})
    else:
        if not (payload.reason or "").strip():
            raise HTTPException(status_code=422, detail="Indiquez le motif : le client le recevra.")
        db.execute(text("UPDATE bookings SET bk_service_status='4', bk_if_cancelled='1', bk_cancellation_reason=:r WHERE bk_id=:i"), {"i": booking_id, "r": payload.reason.strip()})
    db.commit()
    sec.log_event(db, "booking_status", role="apprenant", account_id=provider.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"{booking_id}:{payload.status}")
    return {"id": booking_id, "status": payload.status}


# --------------------------------------------------------------------------- devis demandes par des clients
@router.get("/quotes")
def my_quotes(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    db.rollback()
    rows = db.query(QuoteRequest).filter(QuoteRequest.vendor_id == provider.id).order_by(QuoteRequest.created_at.desc()).limit(100).all()
    return [quote_out(r) for r in rows]


class QuoteReply(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=3, max_length=5000)


@router.post("/quotes/{quote_id}/reply")
@limiter.limit("60/hour")
def reply_quote(request: Request, quote_id: int, payload: QuoteReply, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    q = db.get(QuoteRequest, quote_id)
    if q is None or q.vendor_id != provider.id:
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    subject, html = quote_mail.render_reply(quote_out(q), payload.subject.strip(), payload.message.strip())
    try:
        quote_mail.deliver(q.email, subject, html, "quote_reply", strict=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="L'e-mail n'a pas pu être envoyé. Réessayez dans un instant.")
    q.status, q.reply_subject, q.reply_message = "answered", payload.subject.strip(), payload.message.strip()
    q.replied_by, q.replied_at = f"prestataire:{provider.id}", datetime.utcnow()
    db.commit()
    return quote_out(q)


# --------------------------------------------------------------------------- agenda
class Slot(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    is_active: bool = True


@router.get("/availability")
def get_availability(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    db.rollback()
    rows = db.query(ProviderAvailability).filter(ProviderAvailability.vendor_id == provider.id).order_by(ProviderAvailability.weekday, ProviderAvailability.start_time).all()
    return [{"weekday": a.weekday, "start_time": a.start_time.strftime("%H:%M"), "end_time": a.end_time.strftime("%H:%M"), "is_active": bool(a.is_active)} for a in rows]


@router.put("/availability")
def put_availability(slots: list[Slot], provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Remplace les plages hebdomadaires du prestataire (c'est ce que le client voit sur sa fiche)."""
    if len(slots) > 42:
        raise HTTPException(status_code=422, detail="Trop de plages.")
    for s in slots:
        if s.end_time <= s.start_time:
            raise HTTPException(status_code=422, detail="L'heure de fin doit être après l'heure de début.")
    db.query(ProviderAvailability).filter(ProviderAvailability.vendor_id == provider.id).delete()
    for s in slots:
        db.add(ProviderAvailability(vendor_id=provider.id, weekday=s.weekday, start_time=s.start_time, end_time=s.end_time, is_active=s.is_active))
    db.commit()
    clear_directory_cache()
    return get_availability(provider, db)


@router.get("/agenda")
def agenda(date_from: str | None = None, days: int = 14, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Missions a venir (hors annulees) sur `days` jours, groupees par date."""
    db.rollback()
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="Date invalide (AAAA-MM-JJ).")
    end = start + timedelta(days=min(max(days, 1), 60))
    rows = db.execute(
        text(f"SELECT b.*, s.s_title {_FROM} WHERE b.bk_vendor_id=:v AND b.bk_date>=:a AND b.bk_date<:z AND (b.bk_service_status IS NULL OR b.bk_service_status NOT IN ('3','4')) ORDER BY b.bk_date, b.bk_time"),
        {"v": provider.id, "a": start, "z": end},
    ).mappings().all()
    return {"from": start.isoformat(), "to": (end - timedelta(days=1)).isoformat(), "items": [_row(r) for r in rows]}


# --------------------------------------------------------------------------- paiements
@router.get("/payments")
def payments(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    db.rollback()
    rows = db.execute(text(f"SELECT b.*, s.s_title {_FROM} WHERE b.bk_vendor_id=:v ORDER BY b.bk_created_at DESC, b.bk_id DESC LIMIT 500"), {"v": provider.id}).mappings().all()
    items = [_row(r) for r in rows]
    done = [i for i in items if i["status"] == "completed"]
    months: dict[str, float] = {}
    for i in done:
        k = (i["created_at"] or "")[:7]
        if k:
            months[k] = months.get(k, 0) + i["total"]
    this = datetime.utcnow().strftime("%Y-%m")
    return {
        "totals": {
            "earned": sum(i["total"] for i in done), "month": months.get(this, 0), "to_receive": sum(i["total"] for i in done if not i["paid"]),
            "pending_missions": sum(i["total"] for i in items if i["status"] == "pending"), "completed_count": len(done),
        },
        "months": [{"month": k, "amount": v} for k, v in sorted(months.items())[-6:]],
        "items": items[:60],
    }


# --------------------------------------------------------------------------- avis
@router.get("/reviews")
def my_reviews(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    db.rollback()
    rows = db.query(Review).filter(Review.prestataire_id == provider.id, Review.status != "rejected").order_by(Review.created_at.desc()).limit(100).all()
    approved = [r.rating for r in rows if r.status == "approved"]
    return {
        "average": round(sum(approved) / len(approved), 1) if approved else None, "count": len(approved),
        "items": [{"id": r.id, "rating": r.rating, "comment": r.comment, "status": r.status, "reply": r.reply, "replied_at": _iso(r.replied_at), "created_at": _iso(r.created_at),
                   "client": (r.client.firstname if r.client else None)} for r in rows],
    }


class ReplyIn(BaseModel):
    reply: str = Field(max_length=1000)


@router.post("/reviews/{review_id}/reply")
def reply_review(review_id: int, payload: ReplyIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    r = db.get(Review, review_id)
    if r is None or r.prestataire_id != provider.id or r.status != "approved":
        raise HTTPException(status_code=404, detail="Avis introuvable.")
    r.reply = payload.reply.strip() or None
    r.replied_at = datetime.utcnow() if r.reply else None
    db.commit()
    invalidate_home_cache()
    clear_directory_cache()
    return {"id": r.id, "reply": r.reply}


# --------------------------------------------------------------------------- profil public (ce que voit le client)
def _profile(db: Session, vid: int) -> ProviderProfile | None:
    return db.query(ProviderProfile).filter(ProviderProfile.vendor_id == vid).first()


def _profile_row(db: Session, vid: int, create: bool = False) -> ProviderProfile | None:
    p = _profile(db, vid)
    if p is None and create:
        p = ProviderProfile(vendor_id=vid)
        db.add(p)
        db.flush()
    return p


@router.get("/public-profile")
def public_profile(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    db.rollback()
    p = _profile(db, provider.id)
    media = db.query(ProviderMedia).filter(ProviderMedia.vendor_id == provider.id).order_by(ProviderMedia.sort_order, ProviderMedia.id).all()
    services = db.execute(
        text("SELECT s_id, s_title, s_min_price, s_is_active, s_image FROM services WHERE s_vendor_id=:v AND (s_is_deleted IS NULL OR s_is_deleted IN (0,'0')) ORDER BY s_id DESC"), {"v": provider.id}
    ).fetchall()
    verified = bool(db.execute(text("SELECT vendor_academy_verified FROM vendors WHERE vendor_id=:v"), {"v": provider.id}).scalar())
    return {
        "verified": verified, "url": f"/profil/{provider.id}",
        "headline": p.headline if p else None, "about": p.about if p else None, "cover_image_url": p.cover_image_url if p else None,
        "years_experience": p.years_experience if p else None, "visit_fee": p.visit_fee if p else None, "service_radius_km": p.service_radius_km if p else None,
        "zone_label": p.zone_label if p else None, "services_note": p.services_note if p else None,
        "media": [{"id": m.id, "kind": m.kind, "url": m.url, "caption": m.caption, "is_active": bool(m.is_active)} for m in media],
        "services": [{"id": s[0], "title": s[1], "min_price": s[2], "is_active": str(s[3]) in ("1", "True"), "image": s[4]} for s in services],
    }


class PublicIn(BaseModel):
    headline: str | None = Field(default=None, max_length=255)
    about: str | None = Field(default=None, max_length=2000)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    visit_fee: int | None = Field(default=None, ge=0, le=1_000_000)
    service_radius_km: int | None = Field(default=None, ge=0, le=500)
    zone_label: str | None = Field(default=None, max_length=255)
    services_note: str | None = Field(default=None, max_length=1000)


@router.put("/public-profile")
def save_public_profile(payload: PublicIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    p = _profile_row(db, provider.id, create=True)
    for k, v in payload.model_dump().items():
        setattr(p, k, (v.strip() or None) if isinstance(v, str) else v)
    db.commit()
    clear_directory_cache()
    invalidate_home_cache()
    return public_profile(provider, db)


async def _image(file: UploadFile) -> str:
    data = await file.read(ef.MAX_FILE_BYTES + 1)
    kind = ef.sniff(data)
    if kind not in ("image/jpeg", "image/png", "image/webp") or len(data) > ef.MAX_FILE_BYTES:
        raise HTTPException(status_code=422, detail="Image : JPG, PNG ou WebP, 5 Mo maximum.")
    try:
        return upload_image(data, kind)
    except ImageUploadError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/public-profile/cover")
@limiter.limit("20/minute")
async def upload_cover(request: Request, file: UploadFile = File(...), provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    url = await _image(file)
    _profile_row(db, provider.id, create=True).cover_image_url = url
    db.commit()
    clear_directory_cache()
    return {"cover_image_url": url}


@router.delete("/public-profile/cover")
def remove_cover(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    p = _profile(db, provider.id)
    if p:
        p.cover_image_url = None
        db.commit()
        clear_directory_cache()
    return {"cover_image_url": None}


@router.post("/public-profile/media", status_code=201)
@limiter.limit("30/minute")
async def add_media(request: Request, file: UploadFile = File(...), caption: str = "", provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    if db.query(ProviderMedia).filter(ProviderMedia.vendor_id == provider.id).count() >= 30:
        raise HTTPException(status_code=422, detail="30 réalisations maximum.")
    url = await _image(file)
    m = ProviderMedia(vendor_id=provider.id, kind="photo", url=url, caption=caption.strip()[:255] or None, sort_order=int(datetime.utcnow().timestamp()) % 1_000_000)
    db.add(m)
    db.commit()
    clear_directory_cache()
    return {"id": m.id, "kind": m.kind, "url": m.url, "caption": m.caption, "is_active": True}


class MediaPatch(BaseModel):
    is_active: bool | None = None
    caption: str | None = Field(default=None, max_length=255)


@router.patch("/public-profile/media/{media_id}")
def patch_media(media_id: int, payload: MediaPatch, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    m = db.get(ProviderMedia, media_id)
    if m is None or m.vendor_id != provider.id:
        raise HTTPException(status_code=404, detail="Réalisation introuvable.")
    if payload.is_active is not None:
        m.is_active = payload.is_active
    if payload.caption is not None:
        m.caption = payload.caption.strip() or None
    db.commit()
    clear_directory_cache()
    return {"id": m.id, "is_active": bool(m.is_active), "caption": m.caption}


@router.delete("/public-profile/media/{media_id}", status_code=204)
def delete_media(media_id: int, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    m = db.get(ProviderMedia, media_id)
    if m is None or m.vendor_id != provider.id:
        raise HTTPException(status_code=404, detail="Réalisation introuvable.")
    db.delete(m)
    db.commit()
    clear_directory_cache()


class VisibilityIn(BaseModel):
    is_active: bool


@router.patch("/services/{service_id}/visibility")
def service_visibility(service_id: int, payload: VisibilityIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Afficher / masquer UN de ses services aux clients (annuaire, fiche, reservation)."""
    r = db.execute(text("UPDATE services SET s_is_active=:a WHERE s_id=:i AND s_vendor_id=:v"), {"a": "1" if payload.is_active else "0", "i": service_id, "v": provider.id})
    db.commit()
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="Service introuvable.")
    clear_directory_cache()
    invalidate_home_cache()
    return {"id": service_id, "is_active": payload.is_active}
