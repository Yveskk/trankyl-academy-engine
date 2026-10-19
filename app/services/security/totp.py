"""Double authentification TOTP (RFC 6238) + codes de secours.

Compatible avec Google Authenticator, Microsoft Authenticator, Authy, 1Password...
(SHA-1, 6 chiffres, pas de 30 s). Aucune dependance externe : HMAC de la bibliotheque standard.

Stockage (colonnes `users.totp_*`, memes noms que l'admin Trankyl) :
  - `totp_secret` : chiffre au repos (Fernet, cle derivee de SECRET_KEY), prefixe `enc:v1:`.
    Un secret sans prefixe (ecrit par l'admin Trankyl) reste lisible : migration transparente.
  - `totp_recovery_codes` : JSON des EMPREINTES des codes de secours (jamais les codes). Les codes
    en clair de l'admin Trankyl restent acceptes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

PERIOD = 30
DIGITS = 6
WINDOW = 1  # tolere +/- 30 s de decalage d'horloge
ISSUER = "Trankyl Academy"
_ENC = "enc:v1:"
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans O/0/I/1


# --------------------------------------------------------------------------- secret
def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("totp-at-rest:" + settings.secret_key).encode()).digest())
    return Fernet(key)


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def seal(secret: str) -> str:
    return _ENC + _fernet().encrypt(secret.encode()).decode()


def unseal(stored: str | None) -> str | None:
    if not stored:
        return None
    if not stored.startswith(_ENC):
        return stored
    try:
        return _fernet().decrypt(stored[len(_ENC):].encode()).decode()
    except InvalidToken:
        return None


def otpauth_uri(secret: str, email: str) -> str:
    label = quote(f"{ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"


# --------------------------------------------------------------------------- codes
def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(value).zfill(DIGITS)


def current_code(secret: str, at: float | None = None) -> str:
    """Utile aux tests."""
    return _code_at(secret, int((at if at is not None else time.time()) // PERIOD))


def verify(secret: str, code: str, last_step: int | None = None, at: float | None = None) -> int | None:
    """Retourne le pas de temps accepte, ou None. `last_step` : un code deja utilise (ou plus ancien)
    est refuse, pour qu'un code observe ne puisse pas etre rejoue."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = int((at if at is not None else time.time()) // PERIOD)
    matched: int | None = None
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if hmac.compare_digest(_code_at(secret, step), code):  # pas de sortie anticipee : temps constant
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


# --------------------------------------------------------------------------- codes de secours
def _normalize(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _hash_recovery(code: str) -> str:
    return "h:" + hmac.new(settings.secret_key.encode(), ("recovery:" + _normalize(code)).encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(n: int = 10) -> tuple[list[str], str]:
    """(codes en clair a montrer UNE fois, JSON des empreintes a stocker)."""
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, json.dumps([_hash_recovery(c) for c in codes])


def consume_recovery(stored: str | None, code: str) -> tuple[bool, str | None]:
    """(valide, nouveau JSON sans ce code). Usage unique."""
    try:
        items = json.loads(stored) if stored else []
    except ValueError:
        return False, stored
    if not isinstance(items, list):
        return False, stored
    h, plain = _hash_recovery(code), _normalize(code)
    for i, item in enumerate(items):
        ok = hmac.compare_digest(str(item), h) or (not str(item).startswith("h:") and hmac.compare_digest(_normalize(str(item)), plain))
        if ok:
            return True, json.dumps(items[:i] + items[i + 1:])
    return False, stored


def recovery_left(stored: str | None) -> int:
    try:
        items = json.loads(stored) if stored else []
        return len(items) if isinstance(items, list) else 0
    except ValueError:
        return 0
