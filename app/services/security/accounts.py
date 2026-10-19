"""Securite des comptes : verrouillage progressif, appareils de confiance,
politique de verification a la connexion, journal d'audit, force du mot de passe.

Principe : on n'ajoute rien aux tables partagees (`vendors`, `clients`,
`users`). Un compte sans ligne `academy_account_security` est un compte
historique jamais verifie : il n'est pas bloque, il est verifie
progressivement a sa prochaine connexion."""
import re
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.security import AccountSecurity, SecurityEvent, TrustedDevice
from app.services.security.codes import new_token, sha256_hex

# Hash d'un mot de passe quelconque : sert a depenser le meme temps de calcul quand le compte
# n'existe pas, pour que la duree de la reponse ne revele pas si un numero est inscrit.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def client_ip(request: Request) -> str | None:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


def client_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:255] if ua else None


# --------------------------------------------------------------------------- journal
def log_event(db: Session, event: str, *, role: str | None = None, account_id: int | None = None, channel: str | None = None,
              success: bool = True, ip: str | None = None, ua: str | None = None, detail: str | None = None) -> None:
    db.add(SecurityEvent(role=role, account_id=account_id, event=event, channel=channel, success=success, ip=ip, user_agent=ua, detail=(detail or None) and detail[:255]))
    db.commit()


# --------------------------------------------------------------------------- etat du compte
def get_security(db: Session, role: str, account_id: int, create: bool = False) -> AccountSecurity | None:
    sec = db.query(AccountSecurity).filter(AccountSecurity.role == role, AccountSecurity.account_id == account_id).first()
    if sec is None and create:
        sec = AccountSecurity(role=role, account_id=account_id)
        db.add(sec)
        db.flush()
    return sec


def lock_remaining_minutes(sec: AccountSecurity | None) -> int:
    if sec and sec.locked_until and sec.locked_until > datetime.utcnow():
        return max(1, int((sec.locked_until - datetime.utcnow()).total_seconds() // 60) + 1)
    return 0


def register_failure(db: Session, role: str, account_id: int, ip: str | None, ua: str | None) -> int:
    """Compte une erreur de mot de passe ; verrouille apres `max_failed_logins` (duree doublee
    a chaque verrouillage successif, plafonnee a 24 h). Retourne les essais restants (0 = verrouille)."""
    sec = get_security(db, role, account_id, create=True)
    sec.failed_attempts = (sec.failed_attempts or 0) + 1
    remaining = max(0, settings.max_failed_logins - sec.failed_attempts)
    if sec.failed_attempts >= settings.max_failed_logins:
        minutes = min(24 * 60, settings.lockout_minutes * (2 ** (sec.lock_count or 0)))
        sec.locked_until = datetime.utcnow() + timedelta(minutes=minutes)
        sec.lock_count = (sec.lock_count or 0) + 1
        sec.failed_attempts = 0
        db.commit()
        log_event(db, "account_locked", role=role, account_id=account_id, success=False, ip=ip, ua=ua, detail=f"{minutes} min")
        return 0
    db.commit()
    log_event(db, "login_failed", role=role, account_id=account_id, success=False, ip=ip, ua=ua)
    return remaining


def register_success(db: Session, role: str, account_id: int, ip: str | None) -> None:
    sec = get_security(db, role, account_id, create=True)
    sec.failed_attempts = 0
    sec.locked_until = None
    sec.lock_count = 0
    sec.last_login_at = datetime.utcnow()
    sec.last_login_ip = ip
    db.commit()


def mark_verified(db: Session, role: str, account_id: int, channel: str) -> None:
    sec = get_security(db, role, account_id, create=True)
    now = datetime.utcnow()
    if channel in ("whatsapp", "sms"):
        sec.phone_verified_at = now
    elif channel == "email":
        sec.email_verified_at = now
    db.commit()


def mark_password_changed(db: Session, role: str, account_id: int) -> None:
    sec = get_security(db, role, account_id, create=True)
    sec.password_changed_at = datetime.utcnow()
    sec.failed_attempts = 0
    sec.locked_until = None
    db.commit()


# --------------------------------------------------------------------------- appareils de confiance
def issue_device(db: Session, role: str, account_id: int, ip: str | None, ua: str | None) -> str:
    raw = new_token(32)
    db.add(
        TrustedDevice(
            role=role, account_id=account_id, token_hash=sha256_hex(raw), label=ua, ip=ip,
            expires_at=datetime.utcnow() + timedelta(days=settings.trusted_device_days),
        )
    )
    db.commit()
    return raw


def is_trusted_device(db: Session, role: str, account_id: int, raw: str | None) -> bool:
    if not raw:
        return False
    dev = db.query(TrustedDevice).filter(TrustedDevice.token_hash == sha256_hex(raw)).first()
    if not dev or dev.revoked_at or dev.expires_at < datetime.utcnow() or dev.role != role or dev.account_id != account_id:
        return False
    dev.last_used_at = datetime.utcnow()
    db.commit()
    return True


def revoke_devices(db: Session, role: str, account_id: int) -> None:
    """Apres un changement de mot de passe : tous les appareils doivent se re-verifier."""
    db.query(TrustedDevice).filter(TrustedDevice.role == role, TrustedDevice.account_id == account_id, TrustedDevice.revoked_at.is_(None)).update(
        {TrustedDevice.revoked_at: datetime.utcnow()}
    )
    db.commit()


# --------------------------------------------------------------------------- politique de connexion
def requires_step_up(db: Session, role: str, account_id: int, device_token: str | None) -> bool:
    """Faut-il un code apres un mot de passe correct ?
      - administrateur : toujours (jamais d'appareil de confiance) ;
      - numero jamais verifie (compte historique) : oui, une fois ;
      - politique "always" : oui ; "new_device" : oui sur tout appareil non reconnu ; "off" : non."""
    policy = settings.login_verification_policy
    if role == "admin":
        return policy != "off"
    if policy == "off":
        return False
    sec = get_security(db, role, account_id)
    if sec is None or (sec.phone_verified_at is None and sec.email_verified_at is None):
        return True
    if policy == "always":
        return True
    return not is_trusted_device(db, role, account_id, device_token)


# --------------------------------------------------------------------------- mot de passe
_COMMON = {
    "12345678", "123456789", "1234567890", "password", "password1", "password123", "azerty123", "azertyuiop", "qwertyuiop",
    "motdepasse", "motdepasse1", "00000000", "11111111", "iloveyou", "trankyl", "trankyl123", "test1234", "admin1234", "abcd1234",
    "azerty1234", "qwerty123", "letmein123", "welcome123",
}


def check_password_strength(password: str, *, email: str | None = None, phone: str | None = None, names: tuple[str, ...] = ()) -> None:
    """Regles volontairement simples et utiles (NIST) : longueur, pas de mot de passe
    courant, pas de donnees personnelles evidentes. Leve ValueError avec un message clair."""
    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caracteres.")
    if len(password) > 72:
        raise ValueError("Le mot de passe est trop long (72 caracteres maximum).")
    low = password.lower()
    if low in _COMMON or re.fullmatch(r"(.)\1+", low) or low in ("abcdefgh", "12341234"):
        raise ValueError("Ce mot de passe est trop courant. Choisissez-en un plus difficile a deviner.")
    if email and low == email.lower():
        raise ValueError("Le mot de passe ne doit pas etre identique a votre email.")
    digits = re.sub(r"\D", "", phone or "")
    if digits and len(digits) >= 6 and digits[-8:] in re.sub(r"\D", "", low):
        raise ValueError("Le mot de passe ne doit pas contenir votre numero de telephone.")
    for n in names:
        if len(n) >= 4 and n.lower() in low:
            raise ValueError("Le mot de passe ne doit pas contenir votre nom.")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[\d\W_]", password)):
        raise ValueError("Utilisez des lettres et au moins un chiffre ou un symbole.")
