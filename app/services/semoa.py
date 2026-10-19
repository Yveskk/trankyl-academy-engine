"""Paiement en ligne SEMOA des reservations.

Reprend a l'identique le fonctionnement du backend Node (trankyl_backend_nodejs, module `payment`) et du site Trankyl :
  - memes identifiants (SEMOA_API_KEY_PROD / SEMOA_LOGIN_PROD / SEMOA_API_REFERENCE_PROD) et meme API ;
  - en-tetes `apisecure` = SHA-256(login + cle + sel) ;
  - commande envoyee a `POST /orders` ; la facture est enregistree dans `payment_invoices` ;
  - SEMOA confirme le paiement par un webhook (JWT HS256 signe avec la cle API) -> `payment_records`, puis la
    reservation passe a "payee" (`bk_payment_status`). Ces identifiants n'ont pas le droit de relire le statut d'une
    commande (HTTP 403 ROLE_API_PSP) : le webhook est donc la seule source de confirmation ; en local, il faut une URL publique
    (tunnel) dans SEMOA_CALLBACK_URL.

Le montant n'est JAMAIS fourni par le navigateur : il vient de la reservation enregistree."""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime

import httpx
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

_log = logging.getLogger("semoa")

# Clients hors Togo : SEMOA n'accepte que des numeros +228 pour Mobile Money, la carte passe par ce terminal (comme le backend Node).
INTERNATIONAL_TERMINAL = "3966692814"
INTERNATIONAL_GATEWAYS = ["Semoa-Orabank-Ngenius"]


class SemoaError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def configured() -> bool:
    return bool(settings.semoa_api_key_prod and settings.semoa_login_prod and settings.semoa_api_reference_prod)


def _headers() -> dict:
    salt = str(int(time.time()))
    secure = hashlib.sha256((settings.semoa_login_prod + settings.semoa_api_key_prod + salt).encode()).hexdigest()
    return {"apisecure": secure, "salt": salt, "login": settings.semoa_login_prod, "apireference": settings.semoa_api_reference_prod, "Content-Type": "application/json"}


def _call(method: str, path: str, json: dict | None = None) -> dict:
    if not configured():
        raise SemoaError("Le paiement en ligne n'est pas configure.", 503)
    try:
        r = httpx.request(method, settings.semoa_endpoint.rstrip("/") + path, json=json, headers=_headers(), timeout=15)
    except httpx.HTTPError as e:
        _log.error("SEMOA injoignable (%s %s) : %s", method, path, e)
        raise SemoaError("Le service de paiement est momentanement indisponible. Reessayez.") from e
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        # Jamais de numero de telephone ni de cle dans les journaux : seulement le statut et le motif renvoye.
        _log.error("SEMOA %s %s -> HTTP %s : %s", method, path, r.status_code, str(data)[:300])
        raise SemoaError("Le paiement en ligne a ete refuse. Reessayez ou choisissez le paiement en especes.")
    return data if isinstance(data, dict) else {}


def _merchant_reference(unique_id: str) -> str:
    return f"{unique_id}-{datetime.now().strftime('%d-%m-%Y-%H-%M-%S')}"


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").split()
    if not parts:
        return "Trankyl", "Client"
    return parts[0], " ".join(parts[1:]) or parts[0]


def _is_togo(phone: str) -> bool:
    return phone.replace(" ", "").lstrip("+").startswith("228")


def _existing_invoice(db: Session, booking_id: int, mode: str, amount: float) -> dict | None:
    """Une facture deja creee pour cette reservation, meme montant, encore non payee : on la reutilise (pas de doublon chez SEMOA)."""
    row = db.execute(
        text(
            "SELECT pay_inv_id, pay_inv_reference, pay_inv_code, pay_inv_bill_url, pay_inv_amount, pay_inv_currency FROM payment_invoices "
            "WHERE pay_inv_owner_id=:b AND pay_inv_discr='booking' AND pay_inv_mode=:m AND pay_inv_amount=:a AND pay_inv_bill_url IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM payment_records r WHERE r.prc_invoice_id = pay_inv_id) ORDER BY pay_inv_id DESC LIMIT 1"
        ),
        {"b": booking_id, "m": mode, "a": amount},
    ).first()
    if not row:
        return None
    return {"order_reference": row[1], "code": row[2], "bill_url": row[3], "amount": row[4], "currency": row[5]}


def create_booking_invoice(db: Session, *, booking_id: int, booking_ref: str, amount: float, phone: str, name: str, vendor_id: int, mode: str = "ALL") -> dict:
    """Cree (ou retrouve) la facture SEMOA d'une reservation et renvoie le lien de paiement (`bill_url`)."""
    amount = float(int(-(-amount // 1)))  # arrondi a l'entier superieur, comme le backend Node
    if amount <= 0:
        raise SemoaError("Montant invalide pour le paiement en ligne.", 422)
    again = _existing_invoice(db, booking_id, mode, amount)
    if again:
        return again

    phone = phone.replace(" ", "")
    togo = _is_togo(phone)
    pay_phone = phone
    if not togo:
        # SEMOA n'accepte que les numeros +228 : repli sur le numero (togolais) du prestataire, comme le backend Node.
        v = db.execute(text("SELECT vendor_phone, vendor_country_code FROM vendors WHERE vendor_id=:v"), {"v": vendor_id}).first()
        if v and v[0]:
            pay_phone = f"+{v[1] or '228'}{v[0]}"
    first, last = _split_name(name)
    merchant_ref = _merchant_reference(booking_ref)
    order: dict = {
        "amount": amount, "description": f"Paiement Réservation {booking_ref}", "merchant_reference": merchant_ref,
        "client": {"lastname": last, "firstname": first, "phone": pay_phone},
    }
    if settings.semoa_callback_url:
        order["callback_url"] = settings.semoa_callback_url
    if not togo:
        order["terminal"] = {"code": INTERNATIONAL_TERMINAL}
        order["payment_gateways"] = INTERNATIONAL_GATEWAYS

    res = _call("POST", "/orders", order)
    if res.get("status") != "success" or not res.get("bill_url"):
        _log.error("SEMOA commande non acceptee (%s) : %s", booking_ref, str(res)[:300])
        raise SemoaError("Le paiement en ligne n'a pas pu etre initialise. Reessayez dans un instant.")
    db.execute(
        text(
            "INSERT INTO payment_invoices (pay_inv_owner_id, pay_inv_discr, pay_inv_code, pay_inv_reference, pay_inv_merchant_ref, pay_inv_bill_url, "
            "pay_inv_amount, pay_inv_currency, pay_inv_created_at, pay_inv_mode) VALUES (:b, 'booking', :code, :ref, :mref, :url, :amt, :cur, :now, :mode)"
        ),
        {"b": booking_id, "code": res.get("code"), "ref": res.get("order_reference"), "mref": merchant_ref, "url": res.get("bill_url"),
         "amt": float(res.get("amount") or amount), "cur": res.get("currency"), "now": datetime.utcnow(), "mode": mode},
    )
    db.commit()
    return {"order_reference": res.get("order_reference"), "code": res.get("code"), "bill_url": res.get("bill_url"), "amount": res.get("amount") or amount, "currency": res.get("currency")}


# --------------------------------------------------------------------------- confirmation du paiement
def _parse_date(raw) -> datetime:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


def apply_payments(db: Session, invoice_id: int, payments: list[dict]) -> bool:
    """Enregistre les paiements recus (une seule fois chacun) puis met a jour la reservation ou l'abonnement. Renvoie True si c'est paye."""
    inv = db.execute(text("SELECT pay_inv_owner_id, pay_inv_mode, pay_inv_discr FROM payment_invoices WHERE pay_inv_id=:i"), {"i": invoice_id}).first()
    if not inv or inv[2] not in ("booking", "subscription"):
        return False
    linking = 1 if inv[2] == "booking" and inv[1] in ("PL", "ALL") else 0
    for p in payments:
        ref = p.get("thirdparty_reference")
        if not ref or db.execute(text("SELECT 1 FROM payment_records WHERE prc_reference=:r"), {"r": ref}).first():
            continue
        db.execute(
            text("INSERT INTO payment_records (prc_invoice_id, prc_reference, prc_amount, prc_date, prc_created_at, prc_partner_linking) VALUES (:i, :r, :a, :d, :n, :l)"),
            {"i": invoice_id, "r": ref, "a": float(p.get("amount") or 0), "d": _parse_date(p.get("payment_date")), "n": datetime.utcnow(), "l": linking},
        )
    db.commit()
    if inv[2] == "subscription":
        return refresh_subscription_payment(db, int(inv[0]))
    return refresh_booking_payment(db, int(inv[0]))


def create_subscription_invoice(db: Session, *, subscription_id: int, amount: float, vendor: dict) -> dict:
    """Facture SEMOA d'un abonnement prestataire (meme commande que le backend Node : `payment_invoices`, discr `subscription`)."""
    amount = float(int(-(-amount // 1)))
    if amount <= 0:
        raise SemoaError("Montant d'abonnement invalide.", 422)
    again = db.execute(
        text(
            "SELECT pay_inv_reference, pay_inv_code, pay_inv_bill_url, pay_inv_amount, pay_inv_currency FROM payment_invoices WHERE pay_inv_owner_id=:s AND pay_inv_discr='subscription' "
            "AND pay_inv_amount=:a AND pay_inv_bill_url IS NOT NULL AND NOT EXISTS (SELECT 1 FROM payment_records r WHERE r.prc_invoice_id = pay_inv_id) ORDER BY pay_inv_id DESC LIMIT 1"
        ),
        {"s": subscription_id, "a": amount},
    ).first()
    if again:
        return {"order_reference": again[0], "code": again[1], "bill_url": again[2], "amount": again[3], "currency": again[4]}
    calling = str(vendor.get("calling_code") or "228").lstrip("+")
    togo = calling == "228"
    merchant_ref = f"{vendor.get('unique_id') or 'SUB'}-{subscription_id}-{int(time.time())}"
    order: dict = {
        "amount": amount, "description": f"Abonnement Prestataire {vendor.get('name') or ''}".strip(), "merchant_reference": merchant_ref,
        "client": {"lastname": vendor.get("name") or "Prestataire", "firstname": "Trankyl", "phone": f"+{calling}{vendor.get('phone') or ''}"},
    }
    if settings.semoa_callback_url:
        order["callback_url"] = settings.semoa_callback_url
    if not togo:
        order["terminal"] = {"code": INTERNATIONAL_TERMINAL}
        order["payment_gateways"] = INTERNATIONAL_GATEWAYS
    res = _call("POST", "/orders", order)
    if res.get("status") != "success" or not res.get("bill_url"):
        _log.error("SEMOA abonnement non accepte (%s) : %s", subscription_id, str(res)[:300])
        raise SemoaError("Le paiement en ligne n'a pas pu etre initialise. Reessayez dans un instant.")
    db.execute(
        text(
            "INSERT INTO payment_invoices (pay_inv_owner_id, pay_inv_discr, pay_inv_code, pay_inv_reference, pay_inv_merchant_ref, pay_inv_bill_url, pay_inv_amount, pay_inv_currency, pay_inv_created_at) "
            "VALUES (:s, 'subscription', :code, :ref, :mref, :url, :amt, :cur, :now)"
        ),
        {"s": subscription_id, "code": res.get("code"), "ref": res.get("order_reference"), "mref": merchant_ref, "url": res.get("bill_url"), "amt": float(res.get("amount") or amount), "cur": res.get("currency"), "now": datetime.utcnow()},
    )
    db.commit()
    return {"order_reference": res.get("order_reference"), "code": res.get("code"), "bill_url": res.get("bill_url"), "amount": res.get("amount") or amount, "currency": res.get("currency")}


def refresh_subscription_payment(db: Session, subscription_id: int) -> bool:
    """Abonnement actif des que le total encaisse couvre son montant ; le prestataire est alors reactive."""
    sub = db.execute(text("SELECT subs_amount, subs_vendor_id FROM subscriptions WHERE subs_id=:i"), {"i": subscription_id}).first()
    if not sub:
        return False
    paid = float(
        db.execute(
            text("SELECT COALESCE(SUM(r.prc_amount),0) FROM payment_records r JOIN payment_invoices i ON r.prc_invoice_id=i.pay_inv_id WHERE i.pay_inv_owner_id=:s AND i.pay_inv_discr='subscription'"),
            {"s": subscription_id},
        ).scalar()
        or 0
    )
    done = paid > 0 and paid >= float(sub[0] or 0)
    db.execute(text("UPDATE subscriptions SET subs_is_active=:a WHERE subs_id=:i"), {"a": 1 if done else 0, "i": subscription_id})
    if done and sub[1]:
        db.execute(text("UPDATE vendors SET vendor_is_active='1' WHERE vendor_id=:v"), {"v": sub[1]})
    db.commit()
    return done


def refresh_booking_payment(db: Session, booking_id: int) -> bool:
    b = db.execute(text("SELECT bk_total_amount, bk_amount_remaining FROM bookings WHERE bk_id=:b"), {"b": booking_id}).first()
    if not b:
        return False
    paid = float(
        db.execute(
            text("SELECT COALESCE(SUM(r.prc_amount),0) FROM payment_records r JOIN payment_invoices i ON r.prc_invoice_id=i.pay_inv_id WHERE i.pay_inv_owner_id=:b AND i.pay_inv_discr='booking'"),
            {"b": booking_id},
        ).scalar()
        or 0
    )

    def num(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    due = num(b[1]) or num(b[0])  # total a payer (service + mise en relation - coupon)
    done = paid > 0 and paid >= due
    if paid > 0:
        db.execute(
            text("UPDATE bookings SET bk_amount_paid=:p, bk_payment_status=:s, bk_cash_status=:s WHERE bk_id=:b"),
            {"p": str(int(paid)), "s": "1" if done else "0", "b": booking_id},
        )
        db.commit()
    return done


def handle_webhook(db: Session, token: str) -> bool:
    """Webhook SEMOA : le corps est un JWT HS256 signe avec la cle API."""
    if not settings.semoa_api_key_prod:
        raise SemoaError("Paiement en ligne non configure.", 503)
    try:
        payload = jwt.decode(token, settings.semoa_api_key_prod, algorithms=["HS256"], options={"verify_aud": False})
    except JWTError as e:
        raise SemoaError("Jeton webhook invalide.", 400) from e
    ref = payload.get("order_reference")
    if not ref:
        raise SemoaError("Jeton webhook invalide.", 400)
    inv = db.execute(text("SELECT pay_inv_id FROM payment_invoices WHERE pay_inv_reference=:r"), {"r": ref}).first()
    if not inv:
        raise SemoaError("Facture introuvable.", 404)
    return apply_payments(db, int(inv[0]), payload.get("payments") or [])
