"""Connexion du panneau admin : mot de passe -> (changement du mot de passe temporaire) -> 2FA.

Etats d'un compte apres un mot de passe correct :
  change_password_required : compte cree par un admin, mot de passe temporaire -> a changer d'abord ;
  verification_required    : compte historique jamais enrole : code email, puis configuration 2FA ;
  mfa_setup_required       : scanner le QR code, confirmer un code, noter les codes de secours ;
  mfa_required             : code de l'application (ou code de secours) a chaque connexion.
Chaque etape est liee a un jeton court (10 min, usage "admin_pre") qui ne donne AUCUN acces a l'API."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import AdminUser
from app.services.access import context as ctx
from app.services.security import accounts as sec
from app.services.security import totp

PRE_MINUTES = 10


class AuthFlowError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def issue_pre(user_id: int, stage: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=PRE_MINUTES)
    return jwt.encode({"purpose": "admin_pre", "stage": stage, "sub": str(user_id), "exp": exp, "n": secrets.token_hex(4)}, settings.secret_key, algorithm=settings.jwt_algorithm)


def read_pre(token: str, *stages: str) -> int:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise AuthFlowError(401, "Session de connexion expirée. Reconnectez-vous.", "expired")
    if claims.get("purpose") != "admin_pre" or claims.get("stage") not in stages:
        raise AuthFlowError(401, "Session de connexion invalide. Reconnectez-vous.", "invalid")
    return int(claims["sub"])


def next_stage(admin: AdminUser, profile) -> str:
    if profile is not None and profile.must_change_password:
        return "change_password"
    return "mfa_verify" if admin.totp_enabled and admin.totp_secret else "mfa_setup"


def issue_session(db: Session, admin: AdminUser, amr: list[str], ip: str | None) -> str:
    sec.register_success(db, "admin", admin.id, ip)
    return create_access_token(subject=str(admin.id), role="admin", amr=amr, expires_minutes=settings.admin_session_minutes)


# --------------------------------------------------------------------------- 2FA : inscription
def begin_enrolment(db: Session, admin: AdminUser) -> dict:
    if admin.totp_enabled and admin.totp_secret:
        raise AuthFlowError(409, "La double authentification est déjà activée.", "already_enabled")
    secret = totp.new_secret()
    admin.totp_secret = totp.seal(secret)  # pas encore actif : totp_enabled reste faux jusqu'a confirmation
    admin.totp_enabled = False
    db.commit()
    return {"secret": secret, "otpauth_uri": totp.otpauth_uri(secret, admin.email), "issuer": totp.ISSUER, "account": admin.email, "digits": totp.DIGITS, "period": totp.PERIOD}


def confirm_enrolment(db: Session, admin: AdminUser, code: str, ip: str | None, ua: str | None) -> list[str]:
    """Verifie le premier code, active la 2FA et retourne les codes de secours (montres UNE seule fois)."""
    secret = totp.unseal(admin.totp_secret)
    if admin.totp_enabled or not secret:
        raise AuthFlowError(409, "Aucune configuration en cours. Recommencez l'étape.", "no_setup")
    profile = ctx.get_profile(db, admin.id, create=True)
    step = totp.verify(secret, code, profile.totp_last_step)
    if step is None:
        left = sec.register_failure(db, "admin", admin.id, ip, ua)
        raise AuthFlowError(401, "Code incorrect. Vérifiez l'heure de votre téléphone et réessayez." + ("" if left else " Compte verrouillé temporairement."), "bad_code")
    codes, stored = totp.new_recovery_codes()
    admin.totp_enabled = True
    admin.totp_recovery_codes = stored
    profile.totp_last_step = step
    profile.totp_enabled_at = datetime.utcnow()
    db.commit()
    sec.log_event(db, "mfa_enabled", role="admin", account_id=admin.id, ip=ip, ua=ua)
    return codes


# --------------------------------------------------------------------------- 2FA : connexion
def verify_second_factor(db: Session, admin: AdminUser, *, code: str | None, recovery_code: str | None, ip: str | None, ua: str | None) -> tuple[list[str], int | None]:
    """Valide un code TOTP (anti-rejeu) ou un code de secours (usage unique).
    Retourne (amr, codes de secours restants ou None)."""
    profile = ctx.get_profile(db, admin.id, create=True)
    if recovery_code:
        ok, stored = totp.consume_recovery(admin.totp_recovery_codes, recovery_code)
        if not ok:
            left = sec.register_failure(db, "admin", admin.id, ip, ua)
            raise AuthFlowError(401, "Code de secours incorrect." + ("" if left else " Compte verrouillé temporairement."), "bad_code")
        admin.totp_recovery_codes = stored
        db.commit()
        sec.log_event(db, "mfa_recovery_used", role="admin", account_id=admin.id, ip=ip, ua=ua, detail=f"{totp.recovery_left(stored)} restants")
        return ["pwd", "recovery"], totp.recovery_left(stored)
    secret = totp.unseal(admin.totp_secret)
    step = totp.verify(secret, code or "", profile.totp_last_step) if secret else None
    if step is None:
        left = sec.register_failure(db, "admin", admin.id, ip, ua)
        raise AuthFlowError(401, "Code incorrect ou déjà utilisé. Attendez le prochain code de l'application." + ("" if left else " Compte verrouillé temporairement."), "bad_code")
    profile.totp_last_step = step
    db.commit()
    return ["pwd", "totp"], None


def require_totp(db: Session, admin: AdminUser, code: str, ip: str | None, ua: str | None) -> None:
    """Re-authentification pour une action sensible (changer son mot de passe, regenerer les codes)."""
    verify_second_factor(db, admin, code=code, recovery_code=None, ip=ip, ua=ua)
