"""Verification par code a usage unique (WhatsApp / SMS / email).

Garde-fous : code hache, expiration, nombre d'essais par code, delai entre deux
envois, plafonds d'envois par destinataire (heure/jour) et par IP (anti
"SMS pumping" et harcelement), indicatifs autorises pour WhatsApp/SMS, reponses
generiques ("code invalide ou expire") qui ne revelent rien sur l'etat de la demande."""
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security import Verification
from app.services.countries import active_countries
from app.services.security.accounts import log_event
from app.services.security.codes import code_matches, generate_code, hash_code
from app.services.security.delivery import DeliveryError, mask_destination, send_code

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
CHANNELS = ("whatsapp", "sms", "email")


class VerificationError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retry_after: int | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.retry_after, self.extra = code, message, status, retry_after, extra or {}


@dataclass
class StartResult:
    request_id: str
    channel: str
    masked: str
    expires_in: int
    resend_in: int
    channels: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- destinations
def normalize_e164(phone: str | None) -> str | None:
    if not phone:
        return None
    p = re.sub(r"[\s().-]", "", phone)
    if p.startswith("00"):
        p = "+" + p[2:]
    return p if E164.match(p) else None


def allowed_dial_codes(db: Session) -> list[str]:
    codes = set(settings.otp_allowed_dial_code_list)
    for c in active_countries(db):
        if c.get("calling_code"):
            codes.add(re.sub(r"\D", "", c["calling_code"]))
    return sorted(codes)


def phone_allowed(db: Session, e164: str | None) -> bool:
    return bool(e164) and any(e164.lstrip("+").startswith(c) for c in allowed_dial_codes(db))


def available_channels(db: Session, phone: str | None, email: str | None) -> list[str]:
    out: list[str] = []
    e164 = normalize_e164(phone)
    if phone_allowed(db, e164):
        out += ["whatsapp", "sms"]
    if email:
        out.append("email")
    return out


def _destination_for(channel: str, phone: str | None, email: str | None) -> str | None:
    return (normalize_e164(phone) if channel in ("whatsapp", "sms") else (email or "").strip().lower() or None)


# --------------------------------------------------------------------------- limites
def _check_send_limits(db: Session, destination: str, ip: str | None) -> None:
    now = datetime.utcnow()
    hour, day = now - timedelta(hours=1), now - timedelta(days=1)
    per_hour = db.query(func.coalesce(func.sum(Verification.send_count), 0)).filter(Verification.destination == destination, Verification.created_at >= hour).scalar() or 0
    per_day = db.query(func.coalesce(func.sum(Verification.send_count), 0)).filter(Verification.destination == destination, Verification.created_at >= day).scalar() or 0
    if per_hour >= settings.otp_max_sends_per_hour_destination or per_day >= settings.otp_max_sends_per_day_destination:
        raise VerificationError("rate_limited", "Trop de codes demandes pour ce contact. Reessayez plus tard.", 429, retry_after=3600)
    if ip:
        ip_hour = db.query(func.coalesce(func.sum(Verification.send_count), 0)).filter(Verification.ip == ip, Verification.created_at >= hour).scalar() or 0
        if ip_hour >= settings.otp_max_sends_per_hour_ip:
            raise VerificationError("rate_limited", "Trop de demandes depuis votre connexion. Reessayez plus tard.", 429, retry_after=3600)


def _deliver(db: Session, row: Verification, code: str, lang: str, ip: str | None, ua: str | None, channels: list[str]) -> None:
    try:
        send_code(row.channel, row.destination, code, lang=lang, purpose=row.purpose)
    except DeliveryError as e:
        log_event(db, "otp_delivery_failed", role=row.role, account_id=row.account_id, channel=row.channel, success=False, ip=ip, ua=ua, detail=str(e)[:200])
        # La demande est conservee : l'utilisateur peut basculer tout de suite sur un autre canal
        # (WhatsApp -> SMS -> email) via /verification/resend, sans retaper son mot de passe.
        row.last_sent_at = datetime.utcnow() - timedelta(seconds=settings.otp_resend_cooldown_seconds)
        db.commit()
        raise VerificationError(
            "delivery_failed", str(e), 502,
            extra={"channel": e.channel, "request_id": row.request_id, "channels": channels, "expires_in": settings.otp_ttl_minutes * 60},
        ) from e
    log_event(db, "otp_sent", role=row.role, account_id=row.account_id, channel=row.channel, ip=ip, ua=ua, detail=row.purpose)


# --------------------------------------------------------------------------- cycle de vie
def start(
    db: Session,
    *,
    purpose: str,
    channel: str,
    phone: str | None,
    email: str | None,
    role: str | None = None,
    account_id: int | None = None,
    payload: dict | None = None,
    ip: str | None = None,
    ua: str | None = None,
    lang: str = "fr",
) -> StartResult:
    if channel not in CHANNELS:
        raise VerificationError("bad_channel", "Canal de verification inconnu.")
    channels = available_channels(db, phone, email)
    if channel not in channels:
        raise VerificationError("channel_unavailable", "Ce canal n'est pas disponible pour ce contact.", extra={"channels": channels})
    destination = _destination_for(channel, phone, email)
    if not destination:
        raise VerificationError("channel_unavailable", "Ce canal n'est pas disponible pour ce contact.", extra={"channels": channels})
    _check_send_limits(db, destination, ip)

    # Une nouvelle demande annule les precedentes encore actives pour le meme usage et le meme contact.
    db.query(Verification).filter(
        Verification.destination == destination, Verification.purpose == purpose, Verification.consumed_at.is_(None)
    ).update({Verification.consumed_at: datetime.utcnow()})

    request_id = str(uuid.uuid4())
    code = generate_code()
    data = dict(payload or {})
    data.update({"phone": normalize_e164(phone), "email": (email or "").strip().lower() or None, "lang": lang})
    row = Verification(
        request_id=request_id, purpose=purpose, role=role, account_id=account_id, channel=channel, destination=destination,
        code_hash=hash_code(request_id, code), max_attempts=settings.otp_max_attempts, last_sent_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=settings.otp_ttl_minutes), payload_json=json.dumps(data), ip=ip, user_agent=ua,
    )
    db.add(row)
    db.commit()
    _deliver(db, row, code, lang, ip, ua, channels)
    return StartResult(request_id, channel, mask_destination(channel, destination), settings.otp_ttl_minutes * 60, settings.otp_resend_cooldown_seconds, channels)


def _get_active(db: Session, request_id: str) -> Verification | None:
    row = db.query(Verification).filter(Verification.request_id == (request_id or "")[:36]).first()
    if row is None or row.consumed_at is not None or row.expires_at < datetime.utcnow():
        return None
    return row


def payload_of(row: Verification) -> dict:
    try:
        return json.loads(row.payload_json or "{}")
    except ValueError:
        return {}


def resend(db: Session, request_id: str, channel: str | None, ip: str | None, ua: str | None) -> StartResult:
    row = _get_active(db, request_id)
    if row is None or row.verified_at is not None:
        raise VerificationError("invalid", "Cette demande a expire. Recommencez.")
    wait = settings.otp_resend_cooldown_seconds - int((datetime.utcnow() - row.last_sent_at).total_seconds())
    if wait > 0:
        raise VerificationError("cooldown", f"Patientez {wait} s avant de demander un nouveau code.", 429, retry_after=wait)
    data = payload_of(row)
    channels = available_channels(db, data.get("phone"), data.get("email"))
    channel = channel or row.channel
    if channel not in channels:
        raise VerificationError("channel_unavailable", "Ce canal n'est pas disponible.", extra={"channels": channels})
    destination = _destination_for(channel, data.get("phone"), data.get("email"))
    _check_send_limits(db, destination, ip)

    code = generate_code()
    row.channel, row.destination = channel, destination
    row.code_hash = hash_code(row.request_id, code)
    row.attempts = 0  # nouveau code : nouveaux essais (le plafond d'envois borne le total)
    row.send_count += 1
    row.last_sent_at = datetime.utcnow()
    row.expires_at = datetime.utcnow() + timedelta(minutes=settings.otp_ttl_minutes)
    db.commit()
    _deliver(db, row, code, data.get("lang", "fr"), ip, ua, channels)
    return StartResult(row.request_id, channel, mask_destination(channel, destination), settings.otp_ttl_minutes * 60, settings.otp_resend_cooldown_seconds, channels)


def verify(db: Session, request_id: str, code: str, *, purpose: str, ip: str | None = None, ua: str | None = None) -> Verification:
    """Controle le code. Succes : `verified_at` pose (la demande reste utilisable une seule fois
    par l'appelant, qui doit appeler `consume`). Echec : message generique."""
    row = _get_active(db, request_id)
    if row is None or row.purpose != purpose:
        raise VerificationError("invalid", "Code invalide ou expire.")
    if row.verified_at is not None:
        raise VerificationError("invalid", "Code invalide ou expire.")
    if row.attempts >= row.max_attempts:
        raise VerificationError("too_many_attempts", "Trop d'essais. Demandez un nouveau code.", 429)
    if not re.fullmatch(r"\d{4,10}", (code or "").strip()) or not code_matches(row.request_id, code, row.code_hash):
        row.attempts += 1
        db.commit()
        left = max(0, row.max_attempts - row.attempts)
        log_event(db, "otp_failed", role=row.role, account_id=row.account_id, channel=row.channel, success=False, ip=ip, ua=ua, detail=f"{left} essais restants")
        raise VerificationError("wrong_code", "Code incorrect.", 400, extra={"attempts_left": left})
    row.verified_at = datetime.utcnow()
    db.commit()
    log_event(db, "otp_verified", role=row.role, account_id=row.account_id, channel=row.channel, ip=ip, ua=ua, detail=row.purpose)
    return row


def consume(db: Session, row: Verification) -> None:
    row.consumed_at = datetime.utcnow()
    db.commit()
