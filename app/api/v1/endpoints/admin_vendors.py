"""Administration des prestataires (CRM) : liste filtrable, creation, modification, activation, services, abonnement,
corbeille et anonymisation. Reprend les fonctions de l'admin Angular Trankyl sur les MEMES tables (`vendors`, `services`,
`subscriptions`) ; la suppression definitive y est remplacee par l'anonymisation (reservations et paiements conserves).

Lecture : `academy.providers.view` ; toute ecriture : `academy.providers.manage`. Tout est limite au pays de l'administrateur."""
from __future__ import annotations

import logging
import re
import secrets
import string
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_admin_ctx, require_access
from app.api.v1.endpoints import provider_account as pa
from app.api.v1.endpoints import provider_services as ps
from app.api.v1.endpoints.directory import clear_directory_cache
from app.api.v1.endpoints.provider_work import _image
from app.core.ids import generate_unique_id
from app.core.phone import normalize_phone_for_storage, phone_lookup_variants
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import Apprenant
from app.services import account_deletion as ad
from app.services.countries import marketplace_country_id, vendor_country_clause
from app.services.home import invalidate_home_cache
from app.services.security import accounts as sec

router = APIRouter(dependencies=[Depends(require_access("providers"))])
_log = logging.getLogger("admin_vendors")

ACADEMY_STATUSES = ("apprentice", "provider", "certified_provider")


def _refresh() -> None:
    clear_directory_cache()
    invalidate_home_cache()


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _vendor(db: Session, vendor_id: int, admin) -> Apprenant:
    clause, params = vendor_country_clause(db, admin.country, "v")
    ok = db.execute(text(f"SELECT 1 FROM vendors v WHERE v.vendor_id=:i AND {clause}"), {"i": vendor_id, **params}).first()
    vendor = db.get(Apprenant, vendor_id) if ok else None
    if not vendor:
        raise HTTPException(status_code=404, detail="Prestataire introuvable.")
    return vendor


_SUB_ACTIVE = "(SELECT MAX(subs_end_date) FROM subscriptions WHERE subs_vendor_id=v.vendor_id AND subs_is_active=1 AND subs_end_date>=:now)"
_DELETED = "COALESCE(v.vendor_account_deleted,'0') IN ('1','true')"
_ACTIVE = "COALESCE(v.vendor_is_active,'1') IN ('1','true','yes')"


# --------------------------------------------------------------------------- liste
@router.get("")
def list_vendors(
    q: str = "", state: str = "all", subscription: str = "", verified: str = "", page: int = 1, page_size: int = 20,
    admin=Depends(get_admin_ctx), db: Session = Depends(get_db),
):
    """Prestataires du pays. `state` : all (hors corbeille) | active | inactive | deleted ; `subscription` : yes | no ; `verified` : yes | no."""
    clause, params = vendor_country_clause(db, admin.country, "v")
    p = {**params, "now": datetime.utcnow()}
    base = [clause]
    if q.strip():
        base.append("(v.vendor_name LIKE :q OR v.vendor_family_name LIKE :q OR v.vendor_phone LIKE :q OR v.vendor_email LIKE :q OR v.vendor_unique_id LIKE :q OR v.vendor_referral_code LIKE :q)")
        p["q"] = f"%{q.strip()}%"
    counts_where = " AND ".join(base)
    counts = db.execute(
        text(f"SELECT COUNT(*), SUM(CASE WHEN {_DELETED} THEN 1 ELSE 0 END), SUM(CASE WHEN NOT ({_DELETED}) AND {_ACTIVE} THEN 1 ELSE 0 END), SUM(CASE WHEN NOT ({_DELETED}) AND NOT ({_ACTIVE}) THEN 1 ELSE 0 END) FROM vendors v WHERE {counts_where}"),
        p,
    ).first()
    total_all, n_deleted, n_active, n_inactive = (int(x or 0) for x in counts)
    where = list(base)
    where.append({"deleted": _DELETED, "active": f"NOT ({_DELETED}) AND {_ACTIVE}", "inactive": f"NOT ({_DELETED}) AND NOT ({_ACTIVE})"}.get(state, f"NOT ({_DELETED})"))
    if subscription in ("yes", "no"):
        where.append(f"{_SUB_ACTIVE} IS {'NOT ' if subscription == 'yes' else ''}NULL")
    if verified in ("yes", "no"):
        where.append(f"COALESCE(v.vendor_academy_verified,0) = {1 if verified == 'yes' else 0}")
    page, page_size = max(1, page), min(max(1, page_size), 100)
    rows = db.execute(
        text(
            "SELECT v.vendor_id, v.vendor_unique_id, v.vendor_name, v.vendor_family_name, v.vendor_phone, v.vendor_email, v.vendor_address_city, v.vendor_is_active, v.vendor_account_deleted, "
            "v.vendor_academy_verified, v.vendor_academy_status, v.vendor_referral_code, v.vendor_image, v.vendor_created_at, v.vendor_if_prof_comp, "
            f"(SELECT COUNT(*) FROM services s WHERE s.s_vendor_id=CAST(v.vendor_id AS CHAR) AND (s.s_is_deleted IS NULL OR s.s_is_deleted NOT IN ('1','true'))) AS n_services, {_SUB_ACTIVE} AS sub_end "
            f"FROM vendors v WHERE {' AND '.join(where)} ORDER BY v.vendor_id DESC LIMIT :lim OFFSET :off"
        ),
        {**p, "lim": page_size, "off": (page - 1) * page_size},
    ).fetchall()
    items = [
        {
            "id": r[0], "unique_id": r[1], "name": " ".join(x for x in (r[2], r[3]) if x), "phone": r[4], "email": r[5] or None, "city": r[6], "is_active": str(r[7]) in ("1", "true", "yes"),
            "deleted": str(r[8]) in ("1", "true"), "verified": bool(r[9]), "academy_status": r[10], "referral_code": r[11], "photo": r[12] if str(r[12] or "").startswith("https://") else None,
            "created_at": _iso(r[13]), "profile_complete": str(r[14]) == "1", "services": int(r[15] or 0), "subscription_until": _iso(r[16]), "has_subscription": r[16] is not None,
        }
        for r in rows
    ]
    shown = {"deleted": n_deleted, "active": n_active, "inactive": n_inactive}.get(state, total_all - n_deleted)
    return {"total": shown, "page": page, "page_size": page_size, "counts": {"all": total_all - n_deleted, "active": n_active, "inactive": n_inactive, "deleted": n_deleted}, "items": items}


# --------------------------------------------------------------------------- fiche
@router.get("/{vendor_id}")
def get_vendor(vendor_id: int, lang: str = "fr", admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor(db, vendor_id, admin)
    v = db.execute(text("SELECT * FROM vendors WHERE vendor_id=:i"), {"i": vendor_id}).mappings().first()
    enrollment = db.execute(text("SELECT enroll_id, enroll_status, enroll_admin_note FROM vendor_enrollments WHERE enroll_vendor_id=:i ORDER BY enroll_id DESC LIMIT 1"), {"i": vendor_id}).first()
    stats = db.execute(
        text(
            "SELECT COUNT(*), SUM(CASE WHEN bk_service_status='2' THEN 1 ELSE 0 END), SUM(CASE WHEN bk_service_status IS NULL OR bk_service_status IN ('0','1') THEN 1 ELSE 0 END) FROM bookings WHERE bk_vendor_id=:i"
        ),
        {"i": vendor_id},
    ).first()
    rating = db.execute(text("SELECT AVG(rating), COUNT(*) FROM academy_reviews WHERE vendor_id=:i AND status='approved'"), {"i": vendor_id}).first()
    hist = pa._history(db, vendor_id)
    return {
        "id": vendor_id, "unique_id": v["vendor_unique_id"], "firstname": v["vendor_name"], "lastname": v["vendor_family_name"], "email": v["vendor_email"], "phone": v["vendor_phone"], "sex": v["vendor_sex"],
        "city": v["vendor_address_city"], "address": v["vendor_address"], "bio": v["vendor_bio"], "photo": v["vendor_image"] if str(v["vendor_image"] or "").startswith("https://") else None,
        "is_active": str(v["vendor_is_active"]) in ("1", "true", "yes"), "deleted": str(v["vendor_account_deleted"]) in ("1", "true"), "verified": bool(v["vendor_academy_verified"]),
        "academy_status": v["vendor_academy_status"], "referral_code": v["vendor_referral_code"], "profile_complete": str(v["vendor_if_prof_comp"]) == "1", "created_at": _iso(v["vendor_created_at"]),
        "enrollment": {"id": enrollment[0], "status": enrollment[1], "admin_note": enrollment[2]} if enrollment else None,
        "stats": {"bookings": int(stats[0] or 0), "completed": int(stats[1] or 0), "pending": int(stats[2] or 0), "rating": round(float(rating[0]), 1) if rating and rating[0] else None, "reviews": int(rating[1] or 0) if rating else 0},
        "subscription": {"active": next((h for h in hist if h["status"] == "active"), None), "history": hist, "pricing": pa._pricing(db)},
    }


class VendorIn(BaseModel):
    firstname: str = Field(min_length=2, max_length=120)
    lastname: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    sex: str | None = Field(default=None, pattern="^(male|female|M|F|)$")
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=2000)
    referral_code: str | None = Field(default=None, max_length=50)
    academy_status: str = "provider"
    verified: bool = False


class VendorCreate(VendorIn):
    phone: str = Field(min_length=6, max_length=20, description="Numero sans l'indicatif")
    calling_code: str = Field(default="228", pattern=r"^\d{1,4}$")
    password: str | None = Field(default=None, min_length=8, max_length=72)


class VendorUpdate(VendorIn):
    phone: str | None = Field(default=None, min_length=6, max_length=20)
    calling_code: str | None = Field(default=None, pattern=r"^\d{1,4}$")


def _check_email(email: str | None) -> str | None:
    email = (email or "").strip() or None
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=422, detail="Adresse e-mail invalide.")
    return email


def _unique(db: Session, phone_e164: str | None, email: str | None, exclude: int | None = None) -> None:
    q = db.query(Apprenant)
    cond = None
    if phone_e164:
        cond = Apprenant.phone.in_(phone_lookup_variants(phone_e164))
    if email:
        cond = (Apprenant.email == email) if cond is None else (cond | (Apprenant.email == email))
    if cond is None:
        return
    row = q.filter(cond).first()
    if row and row.id != exclude:
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec ce numéro ou cet e-mail.")


@router.post("", status_code=201)
def create_vendor(request: Request, payload: VendorCreate, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    if payload.academy_status not in ACADEMY_STATUSES:
        raise HTTPException(status_code=422, detail="Statut Academy invalide.")
    email = _check_email(payload.email)
    digits = re.sub(r"\D", "", payload.phone)
    phone = f"+{payload.calling_code}{digits}"
    _unique(db, phone, email)
    password = payload.password or "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    country_id = marketplace_country_id(db, admin.country)
    account = Apprenant(
        vendor_unique_id=generate_unique_id("VEN"), vendor_name=payload.firstname.strip(), email=email or "", phone=normalize_phone_for_storage(phone), hashed_password=hash_password(password),
        academy_status=payload.academy_status, is_active_raw="1", created_at=datetime.utcnow(), country_id=country_id, country_code=admin.country, address_city=(payload.city or None),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    _apply(db, account.id, payload, creating=True)
    sec.log_event(db, "admin_vendor_created", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{account.id}")
    _refresh()
    return {"id": account.id, "temp_password": None if payload.password else password}


def _apply(db: Session, vendor_id: int, p: VendorIn, creating: bool = False) -> None:
    sets = {
        "vendor_family_name": (p.lastname or "").strip() or None, "vendor_sex": p.sex or None, "vendor_address": (p.address or "").strip() or None, "vendor_bio": (p.bio or "").strip() or None,
        "vendor_referral_code": (p.referral_code or "").strip() or None, "vendor_academy_status": p.academy_status, "vendor_academy_verified": 1 if p.verified else 0,
        "vendor_academy_verified_at": datetime.utcnow() if p.verified else None,
    }
    if not creating:
        sets.update({"vendor_name": p.firstname.strip(), "vendor_email": _check_email(p.email), "vendor_address_city": (p.city or "").strip() or None})
    have = {r[0] for r in db.execute(text("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='vendors'")).fetchall()}
    sets = {k: v for k, v in sets.items() if k in have}
    db.execute(text("UPDATE vendors SET " + ", ".join(f"{k}=:{k}" for k in sets) + " WHERE vendor_id=:_id"), {**sets, "_id": vendor_id})
    db.commit()


@router.put("/{vendor_id}")
def update_vendor(request: Request, vendor_id: int, payload: VendorUpdate, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    vendor = _vendor(db, vendor_id, admin)
    if payload.academy_status not in ACADEMY_STATUSES:
        raise HTTPException(status_code=422, detail="Statut Academy invalide.")
    email = _check_email(payload.email)
    phone = None
    if payload.phone:
        phone = f"+{payload.calling_code or '228'}{re.sub(r'\D', '', payload.phone)}"
    _unique(db, phone, email, exclude=vendor.id)
    if phone:
        db.execute(text("UPDATE vendors SET vendor_phone=:p WHERE vendor_id=:i"), {"p": normalize_phone_for_storage(phone), "i": vendor_id})
        db.commit()
    _apply(db, vendor_id, payload)
    sec.log_event(db, "admin_vendor_updated", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id}")
    _refresh()
    return {"id": vendor_id}


class ActiveIn(BaseModel):
    active: bool


@router.post("/{vendor_id}/status")
def set_status(request: Request, vendor_id: int, payload: ActiveIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Active ou desactive le compte (un compte desactive ne peut plus se connecter et disparait du site)."""
    _vendor(db, vendor_id, admin)
    db.execute(text("UPDATE vendors SET vendor_is_active=:a WHERE vendor_id=:i"), {"a": "1" if payload.active else "0", "i": vendor_id})
    db.commit()
    sec.log_event(db, "admin_vendor_status", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id} -> {'actif' if payload.active else 'inactif'}")
    _refresh()
    return {"id": vendor_id, "is_active": payload.active}


# --------------------------------------------------------------------------- corbeille / anonymisation
@router.get("/{vendor_id}/deletion-preview")
def deletion_preview(vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor(db, vendor_id, admin)
    one = lambda sql: int(db.execute(text(sql), {"i": vendor_id, "s": str(vendor_id)}).scalar() or 0)  # noqa: E731
    return {
        "blockers": ad.blockers(db, vendor_id), "grace_days": ad.GRACE_DAYS,
        "bookings": one("SELECT COUNT(*) FROM bookings WHERE bk_vendor_id=:i"), "services": one("SELECT COUNT(*) FROM services WHERE s_vendor_id=:s"),
        "reviews": one("SELECT COUNT(*) FROM academy_reviews WHERE vendor_id=:i"), "subscriptions": one("SELECT COUNT(*) FROM subscriptions WHERE subs_vendor_id=:i"),
        "pending": ad.pending_row(db, vendor_id) is not None,
    }


@router.delete("/{vendor_id}")
def delete_vendor(request: Request, vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Met le compte a la corbeille : desactive, masque, puis anonymise automatiquement a l'echeance du delai (reconnexion = annulation)."""
    _vendor(db, vendor_id, admin)
    blocking = ad.blockers(db, vendor_id)
    if blocking:
        raise HTTPException(status_code=409, detail={"message": "Ce prestataire a des missions ou demandes en cours.", "blockers": blocking})
    due = ad.request_deletion(db, vendor_id)
    sec.log_event(db, "admin_vendor_deleted", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id}")
    return {"id": vendor_id, "anonymize_on": due.isoformat()}


@router.post("/{vendor_id}/restore")
def restore_vendor(request: Request, vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor(db, vendor_id, admin)
    already_anonymous = db.execute(text("SELECT 1 FROM academy_account_deletions WHERE vendor_id=:i AND status='done' LIMIT 1"), {"i": vendor_id}).first()
    if already_anonymous:
        raise HTTPException(status_code=409, detail="Ce compte est déjà anonymisé : ses données ne sont plus récupérables.")
    if not ad.cancel_if_pending(db, vendor_id):
        db.execute(text("UPDATE vendors SET vendor_account_deleted=0, vendor_is_active='1' WHERE vendor_id=:i"), {"i": vendor_id})
        db.commit()
    sec.log_event(db, "admin_vendor_restored", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id}")
    _refresh()
    return {"id": vendor_id}


class AnonymizeIn(BaseModel):
    confirm: str


@router.post("/{vendor_id}/anonymize")
def anonymize_now(request: Request, vendor_id: int, payload: AnonymizeIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Anonymisation immediate et IRREVERSIBLE (equivalent de la suppression definitive d'Angular, sans perdre l'historique comptable)."""
    _vendor(db, vendor_id, admin)
    if payload.confirm != "ANONYMISER":
        raise HTTPException(status_code=422, detail="Tapez ANONYMISER pour confirmer.")
    blocking = ad.blockers(db, vendor_id)
    if blocking:
        raise HTTPException(status_code=409, detail={"message": "Ce prestataire a des missions ou demandes en cours.", "blockers": blocking})
    ad.anonymize(db, vendor_id)
    db.execute(text("UPDATE academy_account_deletions SET status='done', anonymized_at=:n WHERE vendor_id=:i AND status IN ('pending','processing')"), {"n": datetime.utcnow(), "i": vendor_id})
    db.execute(text("INSERT INTO academy_account_deletions (vendor_id, status, requested_at, scheduled_for, anonymized_at) SELECT :i, 'done', :n, :n, :n FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM academy_account_deletions WHERE vendor_id=:i AND status='done')"), {"i": vendor_id, "n": datetime.utcnow()})
    db.commit()
    sec.log_event(db, "admin_vendor_anonymized", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id}")
    _refresh()
    return {"id": vendor_id, "anonymized": True}


# --------------------------------------------------------------------------- services du prestataire
@router.get("/{vendor_id}/services")
def vendor_services(vendor_id: int, lang: str = "fr", admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    vendor = _vendor(db, vendor_id, admin)
    rows = db.execute(text(ps._SELECT + " ORDER BY s.s_id DESC LIMIT 200"), {"v": str(vendor.id)}).fetchall()
    lk = ps._lookups(db, rows, lang)
    items = [ps._out(r, lk, lang, detail=False) for r in rows]
    return {"total": len(items), "active": sum(1 for i in items if i["is_active"]), "limit": ps.MAX_SERVICES, "items": items}


@router.get("/{vendor_id}/service-form")
def service_form(vendor_id: int, lang: str = "fr", admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Metiers et zones utiles au formulaire de service (zones = celles du pays du prestataire)."""
    vendor = _vendor(db, vendor_id, admin)
    return {"catalog": ps.catalog(lang, vendor, db), "locations": ps.locations(vendor, db)}


@router.post("/{vendor_id}/service-images", status_code=201)
async def upload_service_image(vendor_id: int, file: UploadFile = File(...), admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor(db, vendor_id, admin)
    return {"url": await _image(file)}


@router.get("/{vendor_id}/services/{service_id}")
def vendor_service(vendor_id: int, service_id: int, lang: str = "fr", admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    vendor = _vendor(db, vendor_id, admin)
    r = ps._load(db, vendor, service_id)
    return ps._out(r, ps._lookups(db, [r], lang), lang)


@router.post("/{vendor_id}/services", status_code=201)
def create_vendor_service(vendor_id: int, payload: ps.ServiceIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    return ps.do_create(db, _vendor(db, vendor_id, admin), payload)


@router.put("/{vendor_id}/services/{service_id}")
def update_vendor_service(vendor_id: int, service_id: int, payload: ps.ServiceIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    return ps.do_update(db, _vendor(db, vendor_id, admin), service_id, payload)


@router.delete("/{vendor_id}/services/{service_id}", status_code=204)
def delete_vendor_service(vendor_id: int, service_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    ps.do_delete(db, _vendor(db, vendor_id, admin), service_id)


@router.patch("/{vendor_id}/services/{service_id}/visibility")
def vendor_service_visibility(vendor_id: int, service_id: int, payload: ActiveIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor(db, vendor_id, admin)
    r = db.execute(text("UPDATE services SET s_is_active=:a WHERE s_id=:i AND s_vendor_id=:v"), {"a": "1" if payload.active else "0", "i": service_id, "v": str(vendor_id)})
    db.commit()
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="Service introuvable.")
    _refresh()
    return {"id": service_id, "is_active": payload.active}


# --------------------------------------------------------------------------- abonnement
class SubscribeIn(BaseModel):
    period: str = Field(default="monthly", pattern="^(monthly|yearly)$")
    amount: int | None = Field(default=None, ge=0, le=100_000_000)


@router.post("/{vendor_id}/subscription", status_code=201)
def activate_subscription(request: Request, vendor_id: int, payload: SubscribeIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Active un abonnement (paiement recu en especes ou par un agent). Si un abonnement est en cours, la periode s'ajoute a sa suite."""
    _vendor(db, vendor_id, admin)
    amount = payload.amount if payload.amount is not None else pa._pricing(db)["yearly" if payload.period == "yearly" else "monthly"]
    active_end = max((datetime.fromisoformat(h["end"]) for h in pa._history(db, vendor_id) if h["status"] == "active"), default=None)
    start = active_end if active_end and active_end > datetime.utcnow() else datetime.utcnow()
    end = pa._add_period(start, payload.period)
    sid = db.execute(
        text("INSERT INTO subscriptions (subs_vendor_id, subs_start_date, subs_end_date, subs_amount, subs_period, subs_is_active, subs_created_at) VALUES (:v, :s, :e, :a, :p, 1, :n)"),
        {"v": vendor_id, "s": start, "e": end, "a": amount, "p": payload.period, "n": datetime.utcnow()},
    ).lastrowid
    db.execute(text("UPDATE vendors SET vendor_is_active='1' WHERE vendor_id=:v AND COALESCE(vendor_account_deleted,'0') NOT IN ('1','true')"), {"v": vendor_id})
    db.commit()
    sec.log_event(db, "admin_subscription_activated", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id}, {payload.period}, {amount}")
    _refresh()
    return {"id": sid, "start": start.isoformat(), "end": end.isoformat()}


@router.post("/{vendor_id}/subscription/deactivate")
def deactivate_subscription(request: Request, vendor_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _vendor(db, vendor_id, admin)
    n = db.execute(text("UPDATE subscriptions SET subs_is_active=0 WHERE subs_vendor_id=:v AND subs_is_active=1"), {"v": vendor_id}).rowcount
    db.commit()
    if not n:
        raise HTTPException(status_code=404, detail="Aucun abonnement actif.")
    sec.log_event(db, "admin_subscription_deactivated", role="admin", account_id=admin.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire #{vendor_id}")
    _refresh()
    return {"id": vendor_id, "deactivated": n}
