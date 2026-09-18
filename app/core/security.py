from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Compte sur `vendors`/`clients` (base partagee Trankyl) : une bonne
    partie des comptes historiques n'ont jamais ete rehashes en bcrypt
    (ancien hash MD5, ou valeur corrompue par un export Excel type
    "1.22346E+13") et certains comptes crees par un admin Trankyl n'ont pas
    de mot de passe du tout (None). Dans ces deux cas la connexion doit
    simplement echouer (mauvais mot de passe), jamais planter — la seule
    voie de recuperation est "mot de passe oublie", qui ecrit un nouveau
    hash bcrypt valide."""
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
