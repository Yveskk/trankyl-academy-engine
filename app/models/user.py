from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Apprenant(Base):
    """Un apprenant Trankyl Academy. Stocke dans la table `vendors` de la
    base partagee du Trankyl Marketplace (MySQL, GreenGeeks) : un apprenant
    certifie EST un prestataire Trankyl, il n'y a plus de table separee.

    `academy_status` ("apprentice" | "certified_provider" | None) distingue
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
    phone: Mapped[str | None] = mapped_column("vendor_phone", String(50), nullable=True)
    is_active_raw: Mapped[str | None] = mapped_column("vendor_is_active", String(10), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("vendor_created_at", DateTime, nullable=True)

    academy_status: Mapped[str | None] = mapped_column("vendor_academy_status", String(20), nullable=True)
    is_verified: Mapped[bool] = mapped_column("vendor_academy_verified", Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column("vendor_academy_verified_at", DateTime, nullable=True)
    reference_notes: Mapped[str | None] = mapped_column("vendor_academy_reference_notes", Text, nullable=True)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="apprenant")  # type: ignore[name-defined]
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="apprenant")  # type: ignore[name-defined]
    certifications: Mapped[list["Certification"]] = relationship(back_populates="apprenant")  # type: ignore[name-defined]

    @property
    def firstname(self) -> str:
        return (self.vendor_name or "").split(" ", 1)[0]

    @property
    def lastname(self) -> str:
        parts = (self.vendor_name or "").split(" ", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def is_active(self) -> bool:
        return self.is_active_raw in ("1", "yes", "true", "Yes", "True")


class AdminUser(Base):
    """Compte administrateur du site Academy : gere la taxonomie et le
    curriculum. Table dediee `academy_admin_users` (base partagee) —
    distincte de `users`/`admin` cote Trankyl marketplace, qui suivent
    leur propre systeme de permissions sans rapport avec l'Academy."""

    __tablename__ = "academy_admin_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    firstname: Mapped[str] = mapped_column(String(255), nullable=False)
    lastname: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
