from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Apprenant(Base):
    """Un apprenant Trankyl Academy. Stocke dans la table `vendors` de la
    base partagee du Trankyl Marketplace (MySQL, GreenGeeks) : un apprenant
    certifie EST un prestataire Trankyl, il n'y a plus de table separee.

    `academy_status` ("apprentice" | "provider" | "certified_provider" | None) distingue
    un apprenant en formation d'un prestataire actif ; les vendors Trankyl
    preexistants sans lien avec l'Academy ont ce champ a None et
    n'apparaissent jamais dans le moteur de matching Academy (voir
    app.services.trust_score.is_matching_eligible).

    `vendors` n'a qu'un champ `vendor_name` (nom complet), pas de
    firstname/lastname separes : `firstname`/`lastname` sont donc de
    simples proprietes Python qui decoupent ce champ, pour ne pas avoir a
    changer tout le reste du code (schemas, endpoints, frontend) qui
    manipule ces deux champs separement depuis le debut du projet."""

    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column("vendor_id", BigInteger, primary_key=True)
    vendor_unique_id: Mapped[str] = mapped_column(String(25), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column("vendor_email", String(255), nullable=True)
    hashed_password: Mapped[str | None] = mapped_column("vendor_password", String(255), nullable=True)
    family_name: Mapped[str | None] = mapped_column("vendor_family_name", String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column("vendor_phone", String(50), nullable=True)
    is_active_raw: Mapped[str | None] = mapped_column("vendor_is_active", String(10), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("vendor_created_at", DateTime, nullable=True)
    sex: Mapped[str | None] = mapped_column("vendor_sex", String(10), nullable=True)
    address_city: Mapped[str | None] = mapped_column("vendor_address_city", String(255), nullable=True)
    # Pays (colonnes du marketplace) : renseigne a l'inscription pour que le compte appartienne au bon pays.
    country_id: Mapped[int | None] = mapped_column("vendor_country_id", BigInteger, nullable=True)
    country_code: Mapped[str | None] = mapped_column("vendor_country_code", String(10), nullable=True)

    academy_status: Mapped[str | None] = mapped_column("vendor_academy_status", String(20), nullable=True)
    is_verified: Mapped[bool] = mapped_column("vendor_academy_verified", Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column("vendor_academy_verified_at", DateTime, nullable=True)
    reference_notes: Mapped[str | None] = mapped_column("vendor_academy_reference_notes", Text, nullable=True)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="apprenant")  # type: ignore[name-defined]
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="apprenant")  # type: ignore[name-defined]
    certifications: Mapped[list["Certification"]] = relationship(back_populates="apprenant")  # type: ignore[name-defined]

    @property
    def firstname(self) -> str:
        if self.family_name:  # profil complete : `vendor_name` = prenoms, `vendor_family_name` = nom (comme l'ancien site)
            return self.vendor_name or ""
        return (self.vendor_name or "").split(" ", 1)[0]

    @property
    def lastname(self) -> str:
        if self.family_name:
            return self.family_name
        parts = (self.vendor_name or "").split(" ", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def is_active(self) -> bool:
        # La colonne est un tinyint(1) : MySQL renvoie l'entier 1 (et non la chaine "1").
        return str(self.is_active_raw).strip().lower() in ("1", "yes", "true")


class AdminUser(Base):
    """Compte administrateur du site Academy = compte staff Trankyl. Table
    `users` (base partagee) : pas de table admin dediee a l'Academy, on
    reutilise directement les comptes du staff Trankyl. `us_user_type_id`
    vaut 1 pour le type "Admin" (permissions `["ADMIN"]` dans
    `user_types`) — les roles plus restreints (graphiste, service client)
    n'ont pas acces au panneau Academy, qui n'a pas de permissions
    granulaires comme le panneau Trankyl."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column("us_id", BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column("email", String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column("password", String(255), nullable=False)
    firstname: Mapped[str] = mapped_column("us_firstname", String(255), nullable=False)
    lastname: Mapped[str | None] = mapped_column("us_lastname", String(255), nullable=True)
    user_type_id: Mapped[int | None] = mapped_column("us_user_type_id", BigInteger, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("us_created_at", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("us_updated_at", DateTime, nullable=True)
    # Double authentification (colonnes partagees avec l'admin Trankyl, migration 0007).
    totp_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_recovery_codes: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserType(Base):
    """Role (table partagee `user_types`). `ust_roles` = JSON des permissions ; la partie Academy
    (cles `academy.*`) est geree ici, le reste appartient a l'admin Trankyl (voir
    app.services.access.permissions)."""

    __tablename__ = "user_types"

    id: Mapped[int] = mapped_column("ust_id", BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column("ust_wording", String(255), nullable=False)
    description: Mapped[str | None] = mapped_column("ust_description", String(255), nullable=True)
    permissions_json: Mapped[str | None] = mapped_column("ust_roles", Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("ust_created_at", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("ust_updated_at", DateTime, nullable=True)


class AdminProfile(Base):
    """Etat d'un compte du panneau Academy (table `academy_admin_profiles`, migration 0007).
    Pas de ligne = compte historique : actif, sans mot de passe temporaire."""

    __tablename__ = "academy_admin_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    all_countries: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Compte dispense de 2FA (migration 0011) : sans effet tant que ALLOW_MFA_EXEMPT n'est pas active sur le serveur.
    mfa_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AdminCountry(Base):
    """Pays accessibles a un administrateur (table `academy_admin_countries`, migration 0008).
    Un super-administrateur ou un profil `all_countries` a acces a tous les pays."""

    __tablename__ = "academy_admin_countries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EntityCountry(Base):
    """Rattachement a un pays d'un objet d'une table partagee (ex. article de blog = `events`),
    sans modifier cette table. Table `academy_entity_countries` (migration 0008)."""

    __tablename__ = "academy_entity_countries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RoleCountry(Base):
    """Pays dans lesquels un role est proposable (table `academy_role_countries`, migration 0009).
    Aucune ligne = proposable partout."""

    __tablename__ = "academy_role_countries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
