from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
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
