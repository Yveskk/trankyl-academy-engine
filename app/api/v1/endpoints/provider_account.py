"""Espace prestataire — abonnement PRO, notifications, partage du profil, aide et suppression du compte.

Reprend les fonctionnalites de l'app prestataire Trankyl (memes tables : `subscriptions`, `payment_invoices`, `notifications`,
`cust_services`). Le paiement en ligne passe par SEMOA ; l'abonnement s'active quand le webhook confirme l'encaissement."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.endpoints.provider_space import get_provider
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import verify_password
from app.db.session import get_db
from app.models.user import Apprenant
from app.services import account_deletion as ad
from app.services import mail, semoa
from app.services.security import accounts as sec

router = APIRouter()
_log = logging.getLogger("provider_account")

DEFAULT_PRICING = {"monthly_amount": 500, "yearly_amount": 10000}
PERIODS = ("monthly", "yearly")


def _iso(d) -> str | None:
    return d.isoformat() if d else None


# --------------------------------------------------------------------------- abonnement PRO
def _pricing(db: Session) -> dict:
    """Tarifs saisis par l'administration (`meta_data`, cle « subscription »), sinon les tarifs par defaut."""
    row = db.execute(text("SELECT mdt_data FROM meta_data WHERE mdt_data LIKE :p ORDER BY mdt_id LIMIT 1"), {"p": '%"subscription"%'}).first()
    try:
        sub = json.loads(row[0]).get("subscription") or {} if row else {}
        return {"monthly": int(float(sub.get("monthly_amount", DEFAULT_PRICING["monthly_amount"]))), "yearly": int(float(sub.get("yearly_amount", DEFAULT_PRICING["yearly_amount"])))}
    except (ValueError, TypeError):
        return {"monthly": DEFAULT_PRICING["monthly_amount"], "yearly": DEFAULT_PRICING["yearly_amount"]}


def _add_period(start: datetime, period: str) -> datetime:
    try:
        return start.replace(year=start.year + 1) if period == "yearly" else _add_month(start)
    except ValueError:  # 29 fevrier
        return start + timedelta(days=365 if period == "yearly" else 30)


def _add_month(d: datetime) -> datetime:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            continue
    return d + timedelta(days=30)


def _history(db: Session, vendor_id: int) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT s.subs_id, s.subs_period, s.subs_amount, s.subs_start_date, s.subs_end_date, s.subs_is_active, s.subs_created_at, "
            "(SELECT COALESCE(SUM(r.prc_amount),0) FROM payment_records r JOIN payment_invoices i ON i.pay_inv_id=r.prc_invoice_id WHERE i.pay_inv_owner_id=s.subs_id AND i.pay_inv_discr='subscription') AS paid, "
            "(SELECT MAX(r.prc_date) FROM payment_records r JOIN payment_invoices i ON i.pay_inv_id=r.prc_invoice_id WHERE i.pay_inv_owner_id=s.subs_id AND i.pay_inv_discr='subscription') AS paid_at, "
            "(SELECT i.pay_inv_bill_url FROM payment_invoices i WHERE i.pay_inv_owner_id=s.subs_id AND i.pay_inv_discr='subscription' ORDER BY i.pay_inv_id DESC LIMIT 1) AS bill_url "
            "FROM subscriptions s WHERE s.subs_vendor_id=:v ORDER BY s.subs_id DESC LIMIT 60"
        ),
        {"v": vendor_id},
    ).fetchall()
    now = datetime.utcnow()
    out = []
    for r in rows:
        amount, paid = float(r[2] or 0), float(r[7] or 0)
        status = "active" if r[5] == 1 and r[4] and r[4] >= now else "expired" if r[5] == 1 else "paid" if paid >= amount > 0 else "pending"
        out.append(
            {
                "id": r[0], "period": r[1] or "monthly", "amount": int(amount), "start": _iso(r[3]), "end": _iso(r[4]), "status": status, "paid": int(paid), "paid_at": _iso(r[8]),
                "created_at": _iso(r[6]), "pay_url": r[9] if status == "pending" else None,
            }
        )
    return out


def _payments(db: Session, vendor_id: int) -> list[dict]:
    """Paiements encaisses pour les abonnements du prestataire (un par transaction SEMOA), du plus recent au plus ancien."""
    rows = db.execute(
        text(
            "SELECT r.prc_reference, r.prc_amount, COALESCE(r.prc_date, r.prc_created_at), i.pay_inv_reference, i.pay_inv_bill_url, i.pay_inv_currency, s.subs_id, s.subs_period, s.subs_start_date, s.subs_end_date "
            "FROM payment_records r JOIN payment_invoices i ON i.pay_inv_id=r.prc_invoice_id AND i.pay_inv_discr='subscription' "
            "JOIN subscriptions s ON s.subs_id=i.pay_inv_owner_id WHERE s.subs_vendor_id=:v ORDER BY COALESCE(r.prc_date, r.prc_created_at) DESC LIMIT 100"
        ),
        {"v": vendor_id},
    ).fetchall()
    return [
        {"reference": r[0], "amount": int(float(r[1] or 0)), "date": _iso(r[2]), "invoice": r[3], "invoice_url": r[4], "currency": r[5] or "XOF", "subscription_id": r[6], "period": r[7] or "monthly",
         "covers_from": _iso(r[8]), "covers_to": _iso(r[9])}
        for r in rows
    ]


@router.get("/subscription")
def subscription(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    hist = _history(db, provider.id)
    active = [h for h in hist if h["status"] == "active"]
    current = max(active, key=lambda h: h["end"]) if active else None
    days_left = max(0, (datetime.fromisoformat(current["end"]) - datetime.utcnow()).days) if current else 0
    return {"pricing": _pricing(db), "currency": "FCFA", "online_payment": semoa.configured(), "current": current, "days_left": days_left, "history": hist, "payments": _payments(db, provider.id), "paid_total": sum(h["paid"] for h in hist)}


class SubscribeIn(BaseModel):
    period: str = Field(default="monthly")


@router.post("/subscription/init", status_code=201)
@limiter.limit("10/minute")
def subscription_init(request: Request, payload: SubscribeIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Cree l'abonnement (inactif) et renvoie le lien de paiement SEMOA. L'activation vient du webhook, jamais du navigateur."""
    if payload.period not in PERIODS:
        raise HTTPException(status_code=422, detail="Formule invalide.")
    if not semoa.configured():
        raise HTTPException(status_code=503, detail="Le paiement en ligne n'est pas disponible. Contactez le support pour payer en espèces.")
    amount = _pricing(db)["yearly" if payload.period == "yearly" else "monthly"]
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Cette formule n'est pas disponible.")
    v = db.execute(
        text("SELECT v.vendor_unique_id, v.vendor_name, v.vendor_phone, COALESCE(c.country_calling_codes, '+228') FROM vendors v LEFT JOIN countries c ON c.country_id=v.vendor_country_id WHERE v.vendor_id=:v"),
        {"v": provider.id},
    ).first()
    # Renouvellement : la nouvelle periode commence a la fin de l'abonnement en cours.
    active_end = max((datetime.fromisoformat(h["end"]) for h in _history(db, provider.id) if h["status"] == "active"), default=None)
    start = active_end if active_end and active_end > datetime.utcnow() else datetime.utcnow()
    # Reutilise un abonnement en attente de la meme formule (pas de doublon si le prestataire reclique).
    pending = db.execute(
        text("SELECT subs_id FROM subscriptions WHERE subs_vendor_id=:v AND subs_is_active=0 AND subs_period=:p AND subs_amount=:a AND subs_created_at > :t ORDER BY subs_id DESC LIMIT 1"),
        {"v": provider.id, "p": payload.period, "a": amount, "t": datetime.utcnow() - timedelta(days=1)},
    ).first()
    if pending:
        sid = int(pending[0])
        db.execute(text("UPDATE subscriptions SET subs_start_date=:s, subs_end_date=:e WHERE subs_id=:i"), {"s": start, "e": _add_period(start, payload.period), "i": sid})
    else:
        sid = db.execute(
            text("INSERT INTO subscriptions (subs_vendor_id, subs_start_date, subs_end_date, subs_amount, subs_period, subs_is_active, subs_created_at) VALUES (:v, :s, :e, :a, :p, 0, :n)"),
            {"v": provider.id, "s": start, "e": _add_period(start, payload.period), "a": amount, "p": payload.period, "n": datetime.utcnow()},
        ).lastrowid
    db.commit()
    try:
        inv = semoa.create_subscription_invoice(db, subscription_id=sid, amount=amount, vendor={"unique_id": v[0], "name": v[1], "phone": v[2], "calling_code": str(v[3]).lstrip("+")})
    except semoa.SemoaError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"subscription_id": sid, "amount": amount, "pay_url": inv["bill_url"]}


# --------------------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(limit: int = 50, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Annonces de Trankyl (a tous) et messages adresses a ce prestataire, les plus recents d'abord."""
    rows = db.execute(
        text("SELECT noti_id, noti_title, noti_desp, noti_created_at, noti_date, noti_to, noti_vendor_id, noti_data FROM notifications WHERE noti_to='all' OR noti_vendor_id=:v ORDER BY noti_id DESC LIMIT :n"),
        {"v": provider.id, "n": min(max(limit, 1), 200)},
    ).fetchall()
    items = []
    for r in rows:
        try:
            data = json.loads(r[7]) if r[7] else None
        except ValueError:
            data = None
        items.append({"id": r[0], "title": r[1], "body": r[2], "date": _iso(r[3]) or r[4], "personal": r[6] is not None, "data": data if isinstance(data, dict) else None})
    return {"items": items, "latest_id": items[0]["id"] if items else 0}


# --------------------------------------------------------------------------- partage du profil
@router.get("/share")
def share(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    slug = db.execute(text("SELECT public_slug FROM academy_provider_profiles WHERE vendor_id=:v"), {"v": provider.id}).scalar()
    v = db.execute(text("SELECT vendor_name, vendor_family_name, vendor_image FROM vendors WHERE vendor_id=:v"), {"v": provider.id}).first()
    return {
        "path": f"/profil/{slug or provider.id}", "name": " ".join(x for x in (v[0], v[1]) if x) if v else "", "photo": v[2] if v and str(v[2] or "").startswith("https://") else None,
        "verified": bool(db.execute(text("SELECT vendor_academy_verified FROM vendors WHERE vendor_id=:v"), {"v": provider.id}).scalar()),
    }


# --------------------------------------------------------------------------- aide et contacts du pays
@router.get("/support")
def support(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Service client Trankyl du pays du prestataire (table `cust_services`), repli sur le pays de reference."""
    code = (provider.country_code or "TG").upper()
    cols = "cust_serv_name, cust_serv_country, cust_serv_city, cust_serv_country_code, cust_serv_first_tel, cust_serv_second_tel, cust_serv_address, cust_serv_map, cust_serv_fb, cust_serv_insta, cust_serv_tiktok, cust_serv_mail"
    r = db.execute(text(f"SELECT {cols} FROM cust_services WHERE UPPER(cust_serv_code)=:c LIMIT 1"), {"c": code}).first() or db.execute(text(f"SELECT {cols} FROM cust_services WHERE UPPER(cust_serv_code)='TG' LIMIT 1")).first()
    if not r:
        return {"available": False, "email": settings.admin_email_list[0] if settings.admin_email_list else None}
    prefix = str(r[3] or "").lstrip("+")
    phones = [f"+{prefix}{t}" for t in (r[4], r[5]) if t]
    return {
        "available": True, "name": r[0], "country": r[1], "city": r[2], "phones": phones, "whatsapp": f"https://wa.me/{phones[0].lstrip('+')}" if phones else None, "address": r[6] or None, "map": r[7] or None,
        "facebook": r[8] or None, "instagram": r[9] or None, "tiktok": r[10] or None, "email": r[11] or None,
    }


# --------------------------------------------------------------------------- suppression du compte
@router.get("/account/deletion")
def deletion_info(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Ce qui bloque la suppression, le delai de reflexion et l'abonnement encore en cours."""
    try:
        return ad.status(db, provider.id)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _log.error("Suppression de compte indisponible : %s", e)
        raise HTTPException(status_code=503, detail="La suppression de compte n'est pas encore disponible (mise à jour de la base en attente).")


class DeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/account/delete")
@limiter.limit("5/minute")
def delete_account(request: Request, payload: DeleteIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Demande de suppression : controles, mot de passe, puis compte desactive pendant le delai de reflexion (reconnexion = annulation).
    A l'echeance les donnees personnelles sont anonymisees ; reservations et paiements sont conserves."""
    if not verify_password(payload.password, provider.hashed_password):
        raise HTTPException(status_code=403, detail="Mot de passe incorrect.")
    try:
        blocking = ad.blockers(db, provider.id)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _log.error("Suppression de compte indisponible : %s", e)
        raise HTTPException(status_code=503, detail="La suppression de compte n'est pas encore disponible (mise à jour de la base en attente).")
    if blocking:
        raise HTTPException(status_code=409, detail={"message": "Terminez d'abord vos missions et demandes en cours.", "blockers": blocking})
    v = db.execute(text("SELECT vendor_name, vendor_email, vendor_phone FROM vendors WHERE vendor_id=:v"), {"v": provider.id}).first()
    due = ad.request_deletion(db, provider.id)
    sec.log_event(db, "account_deletion_requested", role="apprenant", account_id=provider.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"prestataire, anonymisation le {due.date()}")
    day = due.strftime("%d/%m/%Y")
    if v and v[1]:
        try:
            mail.send_email(
                v[1], "Votre suppression de compte Trankyl est programmée",
                f"<p>Bonjour {v[0] or ''},</p><p>Nous avons bien reçu votre demande de suppression. Votre profil n'est plus visible. Vos données personnelles seront définitivement anonymisées le <strong>{day}</strong>.</p>"
                f"<p>Vous avez changé d'avis ? Il suffit de vous reconnecter avant cette date : votre compte sera rétabli.</p><p>Si vous n'êtes pas à l'origine de cette demande, reconnectez-vous immédiatement et changez votre mot de passe.</p>",
            )
        except Exception as e:  # noqa: BLE001  (non bloquant)
            _log.warning("E-mail de suppression non envoye : %s", e)
    for to in settings.admin_email_list:
        try:
            mail.send_email(to, "Suppression de compte prestataire", f"<p>Le prestataire <strong>{(v[0] or '') if v else ''}</strong> (#{provider.id}) a demandé la suppression de son compte. Anonymisation prévue le {day}.</p>")
        except Exception as e:  # noqa: BLE001
            _log.warning("Alerte suppression non envoyee : %s", e)
    return {"scheduled": True, "anonymize_on": due.isoformat(), "grace_days": ad.GRACE_DAYS}
