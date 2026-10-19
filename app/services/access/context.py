"""Contexte d'acces d'un administrateur : role, permissions effectives, statut du compte."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.user import AdminCountry, AdminProfile, AdminUser, UserType
from app.services.access import permissions as perms


@dataclass
class Access:
    is_super: bool = False
    keys: set[str] = field(default_factory=set)
    role_id: int | None = None
    role_name: str | None = None
    status: str = "active"
    must_change_password: bool = False
    all_countries: bool = False
    countries: set[str] = field(default_factory=set)

    def has(self, key: str) -> bool:
        return self.is_super or key in self.keys

    def in_country(self, code: str) -> bool:
        return self.is_super or self.all_countries or code in self.countries

    @property
    def can_enter(self) -> bool:
        return self.status == "active" and (self.is_super or bool(self.keys)) and (self.is_super or self.all_countries or bool(self.countries))


def get_profile(db: Session, user_id: int, create: bool = False) -> AdminProfile | None:
    p = db.query(AdminProfile).filter(AdminProfile.user_id == user_id).first()
    if p is None and create:
        p = AdminProfile(user_id=user_id)
        db.add(p)
        db.flush()
    return p


def load_access(db: Session, admin: AdminUser) -> Access:
    role = db.get(UserType, admin.user_type_id) if admin.user_type_id else None
    raw = perms.parse(role.permissions_json) if role else []
    is_super, keys = perms.effective(raw)
    profile = get_profile(db, admin.id)
    codes = {r[0] for r in db.query(AdminCountry.country_code).filter(AdminCountry.user_id == admin.id).all()}
    return Access(
        is_super=is_super,
        keys=set(keys),
        role_id=role.id if role else None,
        role_name=role.name if role else None,
        status=profile.status if profile else "active",
        must_change_password=bool(profile.must_change_password) if profile else False,
        all_countries=bool(is_super or (profile.all_countries if profile else False)),
        countries=codes,
    )
