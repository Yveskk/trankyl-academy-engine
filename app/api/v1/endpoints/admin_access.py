"""Gestion des utilisateurs et des roles du panneau admin.

Regles de securite (inspirees des pratiques des grandes organisations) :
  - principe du moindre privilege : un role ne contient que ce qu'on coche ; "voir" est implicite ;
  - pas d'escalade : on ne peut accorder / modifier que des droits qu'on possede soi-meme ;
  - on ne modifie jamais son propre role, on ne se suspend pas soi-meme ;
  - le dernier super-administrateur actif ne peut etre ni suspendu ni retrograde ;
  - pas de suppression de compte (table partagee avec Trankyl) : suspension, immediate et reversible ;
  - mot de passe temporaire a usage unique + 2FA obligatoire a la premiere connexion ;
  - tout est trace dans le journal d'audit (`academy_security_events`)."""
import json
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_admin_ctx, get_current_admin, require_permission
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.db.session import get_db
from app.models.security import AccountSecurity, SecurityEvent
from app.core import country as ctry
from app.models.user import AdminCountry, AdminProfile, AdminUser, EntityCountry, RoleCountry, UserType
from app.services.access import context as ctx
from app.services.access import permissions as perms
from app.services.security import accounts as sec
from app.services.security import delivery

router = APIRouter()


# ===================================================================== schemas
class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] = []
    # Pays dans lesquels le role est proposable. Vide = tous les pays (reserve a qui a acces a tous les pays).
    countries: list[str] = []


class UserCreate(BaseModel):
    firstname: str = Field(min_length=1, max_length=100)
    lastname: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role_id: int
    # Pays auxquels l'utilisateur a acces (au moins un), ou tous les pays.
    countries: list[str] = []
    all_countries: bool = False


class UserUpdate(BaseModel):
    firstname: str = Field(min_length=1, max_length=100)
    lastname: str = Field(min_length=1, max_length=100)
    role_id: int
    countries: list[str] | None = None
    all_countries: bool | None = None


# ===================================================================== helpers
def _audit(db: Session, actor: AdminUser, event: str, target: int | None, detail: str, request: Request) -> None:
    sec.log_event(db, event, role="admin", account_id=target, ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"par #{actor.id} : {detail}"[:255])


def _clean_countries(db: Session, admin: AdminUser, codes: list[str], all_countries: bool, *, required: bool) -> tuple[list[str], bool]:
    """Valide l'attribution de pays : codes connus, au moins un (ou "tous"), et jamais plus large que
    l'acces de celui qui l'accorde (un responsable du Togo ne peut pas ouvrir la Cote d'Ivoire)."""
    access = admin.access  # type: ignore[attr-defined]
    known = set(ctry.known_codes(db))
    out: list[str] = []
    for c in codes:
        code = ctry.normalize(c)
        if not code or code not in known:
            raise HTTPException(status_code=422, detail=f"Pays inconnu : {c}.")
        if code not in out:
            out.append(code)
    if all_countries and not (access.is_super or access.all_countries):
        raise HTTPException(status_code=403, detail="Seul un administrateur ayant accès à tous les pays peut accorder l'accès à tous les pays.")
    for code in out:
        if not access.in_country(code):
            raise HTTPException(status_code=403, detail=f"Vous n'avez pas accès au pays {code} : vous ne pouvez pas l'attribuer.", headers={"X-Missing-Country": code})
    if required and not all_countries and not out:
        raise HTTPException(status_code=422, detail="Choisissez au moins un pays (ou « tous les pays »).")
    return out, all_countries


def _set_user_countries(db: Session, user_id: int, codes: list[str], all_countries: bool) -> None:
    p = ctx.get_profile(db, user_id, create=True)
    p.all_countries = all_countries
    db.query(AdminCountry).filter(AdminCountry.user_id == user_id).delete()
    for c in codes:
        db.add(AdminCountry(user_id=user_id, country_code=c))


def _target_in_scope(admin: AdminUser, target_all: bool, target_codes: set[str]) -> bool:
    """Un administrateur ne gere un compte que si TOUS les pays de ce compte sont dans son perimetre."""
    access = admin.access  # type: ignore[attr-defined]
    if access.is_super or access.all_countries:
        return True
    return not target_all and bool(target_codes) and all(access.in_country(c) for c in target_codes)


def _norm(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


def _is_super_role(role: UserType | None) -> bool:
    return bool(role) and perms.SUPER in perms.parse(role.permissions_json)


def _role_keys(role: UserType) -> set[str]:
    return set(perms.effective(perms.parse(role.permissions_json))[1])


def _need_any(admin: AdminUser, *keys: str) -> None:
    if not any(admin.access.has(k) for k in keys):  # type: ignore[attr-defined]
        raise forbidden(keys[0])


def _assert_can_grant(admin: AdminUser, keys: set[str]) -> None:
    access = admin.access  # type: ignore[attr-defined]
    if access.is_super:
        return
    missing = sorted(k for k in keys if not access.has(k))
    if missing:
        raise HTTPException(status_code=403, detail="Vous ne pouvez accorder que des permissions que vous possédez vous-même.", headers={"X-Missing-Permission": missing[0]})


def _assert_can_assign_role(admin: AdminUser, role: UserType) -> None:
    access = admin.access  # type: ignore[attr-defined]
    if access.is_super:
        return
    if _is_super_role(role):
        raise HTTPException(status_code=403, detail="Seul un super-administrateur peut attribuer ce rôle.")
    _assert_can_grant(admin, _role_keys(role))


def _active_supers(db: Session, excluding: int | None = None) -> int:
    supers = [r.id for r in db.query(UserType).all() if _is_super_role(r)]
    if not supers:
        return 0
    suspended = {p.user_id for p in db.query(AdminProfile).filter(AdminProfile.status == "suspended").all()}
    q = db.query(AdminUser).filter(AdminUser.user_type_id.in_(supers))
    return sum(1 for u in q.all() if u.id != excluding and u.id not in suspended)


def _temp_password() -> str:
    """14 caracteres, sans ambiguite visuelle, avec lettres, chiffres et symbole (passe la politique)."""
    letters, digits, symbols = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz", "23456789", "!@#$%&*?"
    chars = [secrets.choice(letters) for _ in range(9)] + [secrets.choice(digits) for _ in range(3)] + [secrets.choice(symbols) for _ in range(2)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _role_countries_map(db: Session, ids: list[int] | None = None) -> dict[int, list[str]]:
    q = db.query(RoleCountry)
    if ids is not None:
        q = q.filter(RoleCountry.role_id.in_(ids))
    out: dict[int, list[str]] = {}
    for r in q.order_by(RoleCountry.country_code).all():
        out.setdefault(r.role_id, []).append(r.country_code)
    return out


def _role_visible(db: Session, role: UserType, admin: AdminUser) -> bool:
    """Un role est proposable dans le pays courant s'il n'est pas restreint, ou s'il inclut ce pays."""
    codes = _role_countries_map(db, [role.id]).get(role.id, [])
    return not codes or admin.country in codes  # type: ignore[attr-defined]


def _set_role_countries(db: Session, role_id: int, codes: list[str]) -> None:
    db.query(RoleCountry).filter(RoleCountry.role_id == role_id).delete()
    for c in codes:
        db.add(RoleCountry(role_id=role_id, country_code=c))


def _role_out(role: UserType, users_count: int, countries: list[str] | None = None) -> dict:
    raw = perms.parse(role.permissions_json)
    is_super = perms.SUPER in raw
    academy = perms.academy_part(raw)
    return {
        "id": role.id, "name": role.name, "description": role.description, "is_super": is_super, "is_system": is_super,
        "permissions": academy, "permissions_count": len(perms.ALL_KEYS) if is_super else len(academy),
        "other_permissions_count": len([p for p in raw if p not in perms.ALL_KEYS and p != perms.SUPER]),
        "users_count": users_count, "countries": countries or [], "is_global": not countries,
        "created_at": role.created_at, "updated_at": role.updated_at,
    }


def _users_out(db: Session, users: list[AdminUser]) -> list[dict]:
    ids = [u.id for u in users]
    roles = {r.id: r for r in db.query(UserType).all()}
    profiles = {p.user_id: p for p in db.query(AdminProfile).filter(AdminProfile.user_id.in_(ids)).all()} if ids else {}
    secs = {s.account_id: s for s in db.query(AccountSecurity).filter(AccountSecurity.role == "admin", AccountSecurity.account_id.in_(ids)).all()} if ids else {}
    countries: dict[int, list[str]] = {}
    for r in (db.query(AdminCountry).filter(AdminCountry.user_id.in_(ids)).order_by(AdminCountry.country_code).all() if ids else []):
        countries.setdefault(r.user_id, []).append(r.country_code)
    out = []
    for u in users:
        role, p, s = roles.get(u.user_type_id), profiles.get(u.id), secs.get(u.id)
        is_super, keys = perms.effective(perms.parse(role.permissions_json)) if role else (False, [])
        out.append({
            "id": u.id, "firstname": u.firstname, "lastname": u.lastname, "email": u.email,
            "role_id": role.id if role else None, "role_name": role.name if role else None,
            "is_super": is_super, "has_access": is_super or bool(keys),
            "status": p.status if p else "active", "must_change_password": bool(p.must_change_password) if p else False,
            "mfa_enabled": bool(u.totp_enabled), "mfa_exempt": bool(settings.allow_mfa_exempt and p and p.mfa_exempt), "invited": bool(p and p.created_by),
            "last_login_at": s.last_login_at if s else None, "locked": sec.lock_remaining_minutes(s) > 0 if s else False,
            "created_at": u.created_at,
            "countries": countries.get(u.id, []),
            "all_countries": bool(is_super or (p.all_countries if p else False)),
        })
    return out


def _get_user(db: Session, user_id: int) -> AdminUser:
    u = db.get(AdminUser, user_id)
    if u is None or u.user_type_id is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return u


def _get_scoped_user(db: Session, admin: AdminUser, user_id: int) -> AdminUser:
    """Utilisateur du pays courant : un compte hors de ce pays est introuvable (et non "interdit")."""
    u = _get_user(db, user_id)
    row = _users_out(db, [u])[0]
    if not (row["all_countries"] or admin.country in row["countries"]):  # type: ignore[attr-defined]
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return u


def _send_invitation(user: AdminUser, role: UserType, temp: str, reset: bool) -> dict:
    """Envoie le mot de passe temporaire. En mode "log" (developpement) rien n'est envoye et le mot de
    passe est renvoye UNE fois a l'administrateur ; en production il ne transite que par l'email."""
    try:
        delivery.send_admin_invitation(user.email, user.firstname, temp, settings.admin_panel_url, role.name, reset=reset)
        sent = True
    except delivery.DeliveryError:
        sent = False
    return {"sent": sent, "temp_password": temp if (settings.otp_delivery_mode != "live" or not sent) else None}


# ===================================================================== catalogue
@router.get("/permissions")
def permissions_catalogue(admin: AdminUser = Depends(get_admin_ctx)):
    _need_any(admin, "academy.roles.view", "academy.users.view", "academy.users.create", "academy.users.edit")
    return perms.catalogue_payload()


# ===================================================================== roles
@router.get("/roles")
def list_roles(admin: AdminUser = Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _need_any(admin, "academy.roles.view", "academy.users.view", "academy.users.create", "academy.users.edit")
    counts = dict(db.query(AdminUser.user_type_id, func.count(AdminUser.id)).group_by(AdminUser.user_type_id).all())
    scopes = _role_countries_map(db)
    # Les roles Trankyl (sans permission Academy) ne sont pas proposes ici ; les autres le sont s'ils couvrent le pays courant.
    return [
        _role_out(r, int(counts.get(r.id, 0)), scopes.get(r.id, []))
        for r in db.query(UserType).order_by(UserType.id).all()
        if not scopes.get(r.id) or admin.country in scopes[r.id]  # type: ignore[attr-defined]
    ]


def _validated_keys(requested: list[str]) -> list[str]:
    unknown = [k for k in requested if k not in perms.ALL_KEYS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Permission inconnue : {unknown[0]}")
    return perms.with_implied(requested)


def _assert_unique_name(db: Session, name: str, excluding: int | None = None) -> None:
    q = db.query(UserType).filter(func.lower(UserType.name) == name.lower())
    if excluding:
        q = q.filter(UserType.id != excluding)
    if q.first():
        raise HTTPException(status_code=409, detail="Un rôle porte déjà ce nom.")


@router.post("/roles", status_code=201)
def create_role(request: Request, payload: RoleIn, admin: AdminUser = Depends(require_permission("academy.roles.manage")), db: Session = Depends(get_db)):
    name = _norm(payload.name)
    _assert_unique_name(db, name)
    keys = _validated_keys(payload.permissions)
    if not keys:
        raise HTTPException(status_code=422, detail="Cochez au moins une permission : un rôle vide ne donnerait accès à rien.")
    _assert_can_grant(admin, set(keys))
    access = admin.access  # type: ignore[attr-defined]
    wanted = payload.countries or ([] if (access.is_super or access.all_countries) else [admin.country])  # type: ignore[attr-defined]
    codes, _ = _clean_countries(db, admin, wanted, False, required=False)
    now = datetime.utcnow()
    role = UserType(name=name, description=(payload.description or "").strip() or None, permissions_json=json.dumps(perms.merge_for_save([], keys)), created_at=now, updated_at=now)
    db.add(role)
    db.flush()
    _set_role_countries(db, role.id, codes)
    db.commit()
    db.refresh(role)
    _audit(db, admin, "role_created", None, f"rôle #{role.id} « {name} » ({len(keys)} permissions, pays {','.join(codes) or 'tous'})", request)
    return _role_out(role, 0, codes)


def _guard_role_edit(admin: AdminUser, role: UserType) -> None:
    if _is_super_role(role):
        raise HTTPException(status_code=403, detail="Le rôle Administrateur est protégé : il ne peut être ni modifié ni supprimé.")
    access = admin.access  # type: ignore[attr-defined]
    if not access.is_super:
        if role.id == access.role_id:
            raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier votre propre rôle.")
        _assert_can_grant(admin, _role_keys(role))  # on ne reduit pas les droits d'un role plus puissant que le sien


@router.put("/roles/{role_id}")
def update_role(request: Request, role_id: int, payload: RoleIn, admin: AdminUser = Depends(require_permission("academy.roles.manage")), db: Session = Depends(get_db)):
    role = db.get(UserType, role_id)
    if role is None or not _role_visible(db, role, admin):
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    _guard_role_edit(admin, role)
    name = _norm(payload.name)
    _assert_unique_name(db, name, excluding=role.id)
    keys = _validated_keys(payload.permissions)
    if not keys and not [p for p in perms.parse(role.permissions_json) if p not in perms.ALL_KEYS]:
        raise HTTPException(status_code=422, detail="Cochez au moins une permission : un rôle vide ne donnerait accès à rien.")
    _assert_can_grant(admin, set(keys))
    access = admin.access  # type: ignore[attr-defined]
    current_codes = _role_countries_map(db, [role.id]).get(role.id, [])
    if not (access.is_super or access.all_countries):
        # on ne peut pas "globaliser" un role, ni toucher aux pays qu'on ne gere pas
        outside = [c for c in current_codes if not access.in_country(c)]
        if not current_codes or outside:
            raise HTTPException(status_code=403, detail="Ce rôle couvre des pays qui ne font pas partie de votre périmètre.")
    wanted = payload.countries if payload.countries else ([] if (access.is_super or access.all_countries) else current_codes or [admin.country])  # type: ignore[attr-defined]
    codes, _ = _clean_countries(db, admin, wanted, False, required=False)
    before = _role_keys(role)
    _set_role_countries(db, role.id, codes)
    role.name = name
    role.description = (payload.description or "").strip() or None
    role.permissions_json = json.dumps(perms.merge_for_save(perms.parse(role.permissions_json), keys))  # les droits Trankyl du role sont conserves
    role.updated_at = datetime.utcnow()
    db.commit()
    added, removed = sorted(set(keys) - before), sorted(before - set(keys))
    _audit(db, admin, "role_updated", None, f"rôle #{role.id} « {name} » : +{len(added)} −{len(removed)}", request)
    count = db.query(func.count(AdminUser.id)).filter(AdminUser.user_type_id == role.id).scalar() or 0
    return _role_out(role, int(count), codes)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(request: Request, role_id: int, admin: AdminUser = Depends(require_permission("academy.roles.manage")), db: Session = Depends(get_db)):
    role = db.get(UserType, role_id)
    if role is None or not _role_visible(db, role, admin):
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    _guard_role_edit(admin, role)
    n = db.query(func.count(AdminUser.id)).filter(AdminUser.user_type_id == role.id).scalar() or 0
    if n:
        raise HTTPException(status_code=409, detail=f"Ce rôle est attribué à {n} utilisateur{'s' if n > 1 else ''} : changez d'abord leur rôle.")
    if any(p not in perms.ALL_KEYS for p in perms.parse(role.permissions_json)):
        raise HTTPException(status_code=409, detail="Ce rôle porte aussi des droits de l'administration Trankyl : il ne peut pas être supprimé d'ici.")
    name = role.name
    db.query(RoleCountry).filter(RoleCountry.role_id == role.id).delete()
    db.delete(role)
    db.commit()
    _audit(db, admin, "role_deleted", None, f"rôle #{role_id} « {name} »", request)


# ===================================================================== utilisateurs
@router.get("/users")
def list_users(q: str = "", status: str = "", role_id: int | None = None, admin: AdminUser = Depends(require_permission("academy.users.view")), db: Session = Depends(get_db)):
    query = db.query(AdminUser).filter(AdminUser.user_type_id.isnot(None))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((AdminUser.email.like(like)) | (AdminUser.firstname.like(like)) | (AdminUser.lastname.like(like)))
    if role_id:
        query = query.filter(AdminUser.user_type_id == role_id)
    rows = _users_out(db, query.order_by(AdminUser.firstname, AdminUser.id).all())
    rows = [r for r in rows if r["all_countries"] or admin.country in r["countries"]]  # type: ignore[attr-defined]
    if status in ("active", "suspended"):
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/users", status_code=201)
@limiter.limit("20/hour")
def create_user(request: Request, payload: UserCreate, admin: AdminUser = Depends(require_permission("academy.users.create")), db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.query(AdminUser.id).filter(func.lower(AdminUser.email) == email).first():
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet email.")
    role = db.get(UserType, payload.role_id)
    if role is None:
        raise HTTPException(status_code=422, detail="Rôle inconnu.")
    if not perms.grants_panel_access(perms.parse(role.permissions_json)):
        raise HTTPException(status_code=422, detail="Ce rôle ne donne accès à aucune partie de l'administration Academy.")
    _assert_can_assign_role(admin, role)
    if not _role_visible(db, role, admin):
        raise HTTPException(status_code=403, detail="Ce rôle n'est pas proposé dans ce pays.")
    codes, all_c = _clean_countries(db, admin, payload.countries or [admin.country], payload.all_countries, required=True)  # type: ignore[attr-defined]
    temp = _temp_password()
    now = datetime.utcnow()
    user = AdminUser(email=email, firstname=_norm(payload.firstname), lastname=_norm(payload.lastname), hashed_password=hash_password(temp), user_type_id=role.id, created_at=now, updated_at=now, totp_enabled=False)
    db.add(user)
    db.flush()
    db.add(AdminProfile(user_id=user.id, status="active", must_change_password=True, created_by=admin.id, all_countries=all_c))
    for c in codes:
        db.add(AdminCountry(user_id=user.id, country_code=c))
    db.commit()
    db.refresh(user)
    _audit(db, admin, "admin_user_created", user.id, f"{email} (rôle « {role.name} », pays {'tous' if all_c else ','.join(codes)})", request)
    return {"user": _users_out(db, [user])[0], "invitation": _send_invitation(user, role, temp, reset=False)}


@router.get("/users/{user_id}")
def get_user(user_id: int, admin: AdminUser = Depends(require_permission("academy.users.view")), db: Session = Depends(get_db)):
    return _users_out(db, [_get_scoped_user(db, admin, user_id)])[0]


def _guard_target(admin: AdminUser, target: AdminUser, db: Session, action: str) -> UserType | None:
    """Garde-fous communs aux actions sur un autre compte."""
    if target.id == admin.id:
        raise HTTPException(status_code=403, detail=f"Vous ne pouvez pas {action} votre propre compte : demandez à un autre administrateur.")
    row = _users_out(db, [target])[0]
    if not _target_in_scope(admin, row["all_countries"], set(row["countries"])):
        raise HTTPException(status_code=403, detail="Ce compte a accès à des pays qui ne font pas partie de votre périmètre.")
    role = db.get(UserType, target.user_type_id) if target.user_type_id else None
    access = admin.access  # type: ignore[attr-defined]
    if role and not access.is_super:
        if _is_super_role(role):
            raise HTTPException(status_code=403, detail="Seul un super-administrateur peut agir sur un super-administrateur.")
        _assert_can_grant(admin, _role_keys(role))  # pas d'action sur un compte plus puissant que soi
    return role


@router.put("/users/{user_id}")
def update_user(request: Request, user_id: int, payload: UserUpdate, admin: AdminUser = Depends(require_permission("academy.users.edit")), db: Session = Depends(get_db)):
    target = _get_scoped_user(db, admin, user_id)
    old_role = _guard_target(admin, target, db, "modifier")
    new_role = db.get(UserType, payload.role_id)
    if new_role is None:
        raise HTTPException(status_code=422, detail="Rôle inconnu.")
    if not perms.grants_panel_access(perms.parse(new_role.permissions_json)):
        raise HTTPException(status_code=422, detail="Ce rôle ne donne accès à aucune partie de l'administration Academy.")
    if new_role.id != target.user_type_id:
        _assert_can_assign_role(admin, new_role)
        if _is_super_role(old_role) and not _is_super_role(new_role) and _active_supers(db, excluding=target.id) == 0:
            raise HTTPException(status_code=409, detail="C'est le dernier super-administrateur actif : il ne peut pas être rétrogradé.")
    changed_role = new_role.id != target.user_type_id
    if payload.countries is not None or payload.all_countries is not None:
        current = _users_out(db, [target])[0]
        want_all = current["all_countries"] if payload.all_countries is None else payload.all_countries
        codes, want_all = _clean_countries(db, admin, payload.countries if payload.countries is not None else current["countries"], want_all, required=True)
        if _is_super_role(new_role):
            want_all = True  # un super-administrateur a toujours acces a tous les pays
        if want_all != current["all_countries"] or set(codes) != set(current["countries"]):
            _set_user_countries(db, target.id, codes, want_all)
    target.firstname, target.lastname, target.user_type_id, target.updated_at = _norm(payload.firstname), _norm(payload.lastname), new_role.id, datetime.utcnow()
    db.commit()
    _audit(db, admin, "admin_user_updated", target.id, f"rôle « {new_role.name} »" if changed_role else "informations", request)
    return _users_out(db, [target])[0]


def _set_status(db: Session, target: AdminUser, status: str) -> None:
    p = ctx.get_profile(db, target.id, create=True)
    p.status = status
    p.suspended_at = datetime.utcnow() if status == "suspended" else None
    db.commit()


@router.post("/users/{user_id}/suspend")
def suspend_user(request: Request, user_id: int, admin: AdminUser = Depends(require_permission("academy.users.suspend")), db: Session = Depends(get_db)):
    target = _get_scoped_user(db, admin, user_id)
    role = _guard_target(admin, target, db, "suspendre")
    if _is_super_role(role) and _active_supers(db, excluding=target.id) == 0:
        raise HTTPException(status_code=409, detail="C'est le dernier super-administrateur actif : il ne peut pas être suspendu.")
    _set_status(db, target, "suspended")
    _audit(db, admin, "admin_user_suspended", target.id, target.email, request)
    return _users_out(db, [target])[0]


@router.post("/users/{user_id}/reactivate")
def reactivate_user(request: Request, user_id: int, admin: AdminUser = Depends(require_permission("academy.users.suspend")), db: Session = Depends(get_db)):
    target = _get_scoped_user(db, admin, user_id)
    _guard_target(admin, target, db, "réactiver")
    _set_status(db, target, "active")
    s = sec.get_security(db, "admin", target.id)
    if s:  # un compte rouvert repart sans verrouillage
        s.failed_attempts, s.locked_until, s.lock_count = 0, None, 0
        db.commit()
    _audit(db, admin, "admin_user_reactivated", target.id, target.email, request)
    return _users_out(db, [target])[0]


@router.post("/users/{user_id}/reset-password")
@limiter.limit("20/hour")
def reset_user_password(request: Request, user_id: int, admin: AdminUser = Depends(require_permission("academy.users.reset")), db: Session = Depends(get_db)):
    """Nouveau mot de passe temporaire (a changer a la prochaine connexion) ; ferme les sessions ouvertes."""
    target = _get_scoped_user(db, admin, user_id)
    role = _guard_target(admin, target, db, "réinitialiser")
    temp = _temp_password()
    target.hashed_password = hash_password(temp)
    p = ctx.get_profile(db, target.id, create=True)
    p.must_change_password = True
    if p.created_by is None:
        p.created_by = admin.id  # l'invitation passe par un admin : plus de verification email prealable
    db.commit()
    sec.mark_password_changed(db, "admin", target.id)
    _audit(db, admin, "admin_password_reset", target.id, target.email, request)
    return {"user": _users_out(db, [target])[0], "invitation": _send_invitation(target, role or UserType(name=""), temp, reset=True)}


@router.post("/users/{user_id}/reset-mfa")
@limiter.limit("20/hour")
def reset_user_mfa(request: Request, user_id: int, admin: AdminUser = Depends(require_permission("academy.users.reset")), db: Session = Depends(get_db)):
    """Telephone perdu : efface la 2FA ; l'utilisateur la reconfigure a sa prochaine connexion."""
    target = _get_scoped_user(db, admin, user_id)
    _guard_target(admin, target, db, "réinitialiser la 2FA de")
    target.totp_enabled, target.totp_secret, target.totp_recovery_codes = False, None, None
    p = ctx.get_profile(db, target.id, create=True)
    p.totp_last_step, p.totp_enabled_at = None, None
    if p.created_by is None:
        p.created_by = admin.id
    db.commit()
    sec.mark_password_changed(db, "admin", target.id)  # ferme les sessions ouvertes
    _audit(db, admin, "admin_mfa_reset", target.id, target.email, request)
    return _users_out(db, [target])[0]


@router.get("/users/{user_id}/events")
def user_events(user_id: int, limit: int = 30, admin: AdminUser = Depends(require_permission("academy.users.view")), db: Session = Depends(get_db)):
    _get_scoped_user(db, admin, user_id)
    rows = db.query(SecurityEvent).filter(SecurityEvent.role == "admin", SecurityEvent.account_id == user_id).order_by(SecurityEvent.id.desc()).limit(min(limit, 100)).all()
    return [{"id": e.id, "event": e.event, "success": bool(e.success), "ip": e.ip, "detail": e.detail, "created_at": e.created_at} for e in rows]
