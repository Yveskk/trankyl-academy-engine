"""Flux de reinitialisation de mot de passe par OTP, inspire de
trankyl_backend_nodejs (meme duree de validite, meme format de code) mais
simplifie : code a 6 chiffres, 15 minutes de validite, stocke dans
`otp_codes`, envoye par email (Mailjet) ou SMS (AfrikSMS) — mêmes
identifiants que le backend Node."""
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.client import Client
from app.models.otp import OtpCode
from app.models.user import AdminUser, Apprenant
from app.services.mail import send_email
from app.services.sms import send_sms

OTP_VALIDITY_MINUTES = 15
MAX_ATTEMPTS = 5

_MODEL_BY_ROLE = {"apprenant": Apprenant, "client": Client, "admin": AdminUser}


def _get_account(db: Session, role: str, email: str):
    model = _MODEL_BY_ROLE.get(role)
    if model is None:
        return None
    return db.query(model).filter(model.email == email).first()


def generate_otp() -> str:
    """6 chiffres, comme trankyl_backend_nodejs (crypto.randomInt equivalent
    cryptographiquement sur — secrets.randbelow)."""
    return str(secrets.randbelow(900000) + 100000)


def request_password_reset(db: Session, email: str, role: str, channel: str) -> None:
    """Ne revele jamais si le compte existe (silencieux si absent). Genere
    et envoie un OTP sinon."""
    account = _get_account(db, role, email)
    if account is None:
        return

    code = generate_otp()
    db.add(
        OtpCode(
            identifier=email,
            role=role,
            purpose="password_reset",
            code=code,
            expires_at=datetime.utcnow() + timedelta(minutes=OTP_VALIDITY_MINUTES),
        )
    )
    db.commit()

    phone = getattr(account, "phone", None)
    if channel == "sms" and phone:
        send_sms(phone, f"TRANKYL: Votre code de verification est {code}")
    else:
        send_email(
            email,
            "Code de verification",
            f"<div>Votre code de verification Trankyl Academy est <strong>{code}</strong>."
            f" Il est valide {OTP_VALIDITY_MINUTES} minutes.</div>",
        )


def verify_otp(db: Session, email: str, role: str, code: str) -> str:
    """Verifie le code le plus recent non utilise. Retourne un reset_token
    (32 octets hex) valable 15 minutes pour l'etape reset-password."""
    otp = (
        db.query(OtpCode)
        .filter(
            OtpCode.identifier == email,
            OtpCode.role == role,
            OtpCode.purpose == "password_reset",
            OtpCode.used.is_(False),
        )
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp or otp.expires_at < datetime.utcnow():
        raise ValueError("Code invalide ou expire")
    if otp.attempts >= MAX_ATTEMPTS:
        raise ValueError("Trop de tentatives — demandez un nouveau code")
    if otp.code != code:
        otp.attempts += 1
        db.commit()
        raise ValueError("Code incorrect")

    otp.used = True

    reset_token = secrets.token_hex(32)
    db.add(
        OtpCode(
            identifier=email,
            role=role,
            purpose="reset_token",
            code=reset_token,
            expires_at=datetime.utcnow() + timedelta(minutes=OTP_VALIDITY_MINUTES),
        )
    )
    db.commit()
    return reset_token


def reset_password(db: Session, email: str, role: str, reset_token: str, new_password: str) -> None:
    token_row = (
        db.query(OtpCode)
        .filter(
            OtpCode.identifier == email,
            OtpCode.role == role,
            OtpCode.purpose == "reset_token",
            OtpCode.code == reset_token,
            OtpCode.used.is_(False),
        )
        .first()
    )
    if not token_row or token_row.expires_at < datetime.utcnow():
        raise ValueError("Jeton de reinitialisation invalide ou expire")

    account = _get_account(db, role, email)
    if account is None:
        raise ValueError("Compte introuvable")

    account.hashed_password = hash_password(new_password)
    token_row.used = True
    db.commit()
