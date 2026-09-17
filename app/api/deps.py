from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.client import Client
from app.models.user import AdminUser, Apprenant

# HTTPBearer (et non OAuth2PasswordBearer) : nos endpoints de login prennent
# un JSON {email, password}, pas le formulaire OAuth2 standard. Ca donne dans
# Swagger un simple champ "coller le token" sur le bouton Authorize, qu'on
# recupere via /auth/login ou /auth/admin/login.
bearer_scheme = HTTPBearer(auto_error=False, description="Coller le access_token obtenu via /auth/login ou /auth/admin/login")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Identifiants invalides ou expires",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_apprenant(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Apprenant:
    if credentials is None:
        raise credentials_exception
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("role") != "apprenant":
        raise credentials_exception
    apprenant = db.get(Apprenant, int(payload["sub"]))
    if apprenant is None or not apprenant.is_active:
        raise credentials_exception
    return apprenant


def get_current_client(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Client:
    if credentials is None:
        raise credentials_exception
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("role") != "client":
        raise credentials_exception
    client = db.get(Client, int(payload["sub"]))
    if client is None or not client.is_active:
        raise credentials_exception
    return client


def get_current_client_or_apprenant(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> tuple[str, int]:
    """Pour les endpoints partages entre clients et prestataires (le fil de
    messages d'un ContactRequest approuve, ou les deux sont parties
    prenantes). Retourne (role, id) : role vaut "client" ou "apprenant"."""
    if credentials is None:
        raise credentials_exception
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_exception
    role = payload.get("role")
    if role == "client":
        client = db.get(Client, int(payload["sub"]))
        if client is None or not client.is_active:
            raise credentials_exception
        return ("client", client.id)
    if role == "apprenant":
        apprenant = db.get(Apprenant, int(payload["sub"]))
        if apprenant is None or not apprenant.is_active:
            raise credentials_exception
        return ("apprenant", apprenant.id)
    raise credentials_exception


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    if credentials is None:
        raise credentials_exception
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("role") != "admin":
        raise credentials_exception
    admin = db.get(AdminUser, int(payload["sub"]))
    if admin is None or not admin.is_active:
        raise credentials_exception
    return admin


def get_optional_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser | None:
    """Comme get_current_admin, mais ne leve jamais : retourne None si pas de
    token / token invalide. Pour les endpoints publics dont seule UNE partie
    du comportement (ex: forcer un recalcul couteux) doit rester reservee
    aux admins."""
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("role") != "admin":
        return None
    admin = db.get(AdminUser, int(payload["sub"]))
    if admin is None or not admin.is_active:
        return None
    return admin
