from datetime import timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.client import Client
from app.core import country as ctry
from app.models.security import AccountSecurity
from app.models.user import AdminUser, Apprenant
from app.services.access.context import load_access

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


def _admin_from_credentials(credentials: HTTPAuthorizationCredentials | None, db: Session) -> AdminUser | None:
    """Jeton "admin" valide + compte existant, actif, avec un role donnant acces au panneau.
    Le statut et les permissions sont relus en base a CHAQUE requete : une suspension ou un
    changement de role prend effet immediatement, sans attendre l'expiration du jeton."""
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("role") != "admin":
        return None
    admin = db.get(AdminUser, int(payload["sub"]))
    if admin is None:
        return None
    access = load_access(db, admin)
    if not access.can_enter:
        return None
    # Un changement / une reinitialisation de mot de passe ferme toutes les sessions ouvertes avant.
    changed = db.query(AccountSecurity.password_changed_at).filter(AccountSecurity.role == "admin", AccountSecurity.account_id == admin.id).scalar()
    if changed is not None and payload.get("iat") is not None and payload["iat"] + 1 < changed.replace(tzinfo=timezone.utc).timestamp():
        return None
    admin.access = access  # type: ignore[attr-defined]
    return admin


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    admin = _admin_from_credentials(credentials, db)
    if admin is None:
        raise credentials_exception
    return admin


def get_optional_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser | None:
    """Comme get_current_admin, mais ne leve jamais : retourne None si pas de
    jeton admin valide. Sert aux endpoints publics qui enrichissent leur reponse
    pour les admins."""
    try:
        return _admin_from_credentials(credentials, db)
    except Exception:
        return None


def current_country(request: Request, db: Session = Depends(get_db)) -> str:
    """Pays d'une requete publique (`?country=` ou `X-Country`, sinon pays par defaut)."""
    return ctry.public_country(request, db)


def current_lang(request: Request) -> str:
    return ctry.request_lang(request)


def resolve_admin_country(request: Request, admin: AdminUser, db: Session) -> str:
    """Pays dans lequel travaille l'administrateur. Un pays demande auquel il n'a pas acces est REFUSE
    (jamais de repli silencieux : une ecriture ne doit pas atterrir dans le mauvais pays)."""
    access = admin.access  # type: ignore[attr-defined]
    wanted = ctry.requested_country(request)
    if wanted:
        if wanted not in ctry.known_codes(db):
            raise HTTPException(status_code=404, detail=f"Pays inconnu : {wanted}.")
        if not access.in_country(wanted):
            raise HTTPException(status_code=403, detail="Vous n'avez pas accès à ce pays.", headers={"X-Missing-Country": wanted})
        return wanted
    default = ctry.default_country(db)
    if access.in_country(default):
        return default
    allowed = [c for c in ctry.known_codes(db) if access.in_country(c)] or sorted(access.countries)
    if not allowed:
        raise HTTPException(status_code=403, detail="Aucun pays ne vous est attribué.")
    return allowed[0]


def get_admin_ctx(request: Request, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)) -> AdminUser:
    """Administrateur + pays de travail (`admin.country`)."""
    admin.country = resolve_admin_country(request, admin, db)  # type: ignore[attr-defined]
    return admin


def forbidden(key: str) -> HTTPException:
    return HTTPException(status_code=403, detail="Vous n'avez pas la permission d'effectuer cette action.", headers={"X-Missing-Permission": key})


def require_permission(*keys: str):
    """Exige TOUTES les permissions listees (ex. `academy.users.create`)."""

    def dependency(admin: AdminUser = Depends(get_admin_ctx)) -> AdminUser:
        for key in keys:
            if not admin.access.has(key):  # type: ignore[attr-defined]
                raise forbidden(key)
        return admin

    return dependency


def require_access(menu: str, write: str = "manage", read: str = "view"):
    """Lecture (GET) -> `academy.<menu>.view` ; toute ecriture -> `academy.<menu>.<write>`."""

    def dependency(request: Request, admin: AdminUser = Depends(get_admin_ctx)) -> AdminUser:
        action = read if request.method in ("GET", "HEAD", "OPTIONS") else write
        key = f"academy.{menu}.{action}"
        if not admin.access.has(key):  # type: ignore[attr-defined]
            raise forbidden(key)
        return admin

    return dependency
