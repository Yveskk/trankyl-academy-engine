"""Generation et verification des codes a usage unique. Le code n'est jamais
stocke en clair : on garde son empreinte HMAC-SHA256 (cle serveur + identifiant
de la demande), comparee en temps constant."""
import hashlib
import hmac
import secrets

from app.core.config import settings


def generate_code() -> str:
    """Code numerique de `otp_code_length` chiffres (aleatoire cryptographique)."""
    n = max(4, settings.otp_code_length)
    return str(secrets.randbelow(10**n)).zfill(n)


def hash_code(request_id: str, code: str) -> str:
    key = f"{settings.secret_key}:otp".encode()
    return hmac.new(key, f"{request_id}:{code}".encode(), hashlib.sha256).hexdigest()


def code_matches(request_id: str, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_code(request_id, (code or "").strip()), expected_hash)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
