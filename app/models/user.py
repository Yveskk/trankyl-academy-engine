from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Apprenant(Base):
    """Un eleve de Trankyl Academy. N'est PAS un vendor Trankyl : le lien
    avec un vendor_id se fera plus tard, quand l'eleve sera active en tant
    que prestataire cote Trankyl."""

    __tablename__ = "apprenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    firstname: Mapped[str] = mapped_column(String(255), nullable=False)
    lastname: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # --- Verification / confiance ---
    # Un apprenant n'est propose dans le moteur de matching (recherche de
    # prestataires + assistant SITA) que s'il est verifie manuellement par un
    # admin (identite / serieux) ET que son score de confiance calcule est au
    # dessus du seuil (voir app.services.trust_score). C'est le "blocage
    # automatique" : aucun contournement possible depuis le matching public.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reference_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="apprenant")
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="apprenant")
    certifications: Mapped[list["Certification"]] = relationship(back_populates="apprenant")


class AdminUser(Base):
    """Compte administrateur du site Academy : gere la taxonomie et le
    curriculum. Distinct des apprenants (permissions differentes)."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    firstname: Mapped[str] = mapped_column(String(255), nullable=False)
    lastname: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
