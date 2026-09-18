from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Enrollment(Base):
    """Inscription d'un apprenant a un module et suivi de sa progression.
    Table `academy_enrollments` (base partagee Trankyl) : la colonne
    physique est `vendor_id` (un apprenant EST un vendor), mappee sur
    l'attribut Python `apprenant_id` pour ne rien changer au reste du
    code."""

    __tablename__ = "academy_enrollments"
    __table_args__ = (UniqueConstraint("vendor_id", "module_id", name="uq_academy_enrollment_vendor_module"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    apprenant_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    module_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_modules.id", ondelete="CASCADE"), nullable=False)
    statut: Mapped[str] = mapped_column(String(20), default="en_cours")  # en_cours | termine
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    apprenant: Mapped["Apprenant"] = relationship(back_populates="enrollments")  # type: ignore[name-defined]
    module: Mapped["Module"] = relationship(back_populates="enrollments")  # type: ignore[name-defined]


class NiveauEnrollment(Base):
    """Inscription d'un apprenant a un niveau complet. Table
    `academy_niveau_enrollments`."""

    __tablename__ = "academy_niveau_enrollments"
    __table_args__ = (UniqueConstraint("vendor_id", "niveau_id", name="uq_academy_niveau_enrollment_vendor_niveau"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    apprenant_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    niveau_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_niveaux.id", ondelete="CASCADE"), nullable=False)
    metier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_metiers.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    apprenant: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
    niveau: Mapped["Niveau"] = relationship()  # type: ignore[name-defined]
    metier: Mapped["Metier"] = relationship()  # type: ignore[name-defined]


class QuizAttempt(Base):
    """Une tentative de quiz par un apprenant. Table
    `academy_quiz_attempts`."""

    __tablename__ = "academy_quiz_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    apprenant_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    quiz_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_quizzes.id", ondelete="CASCADE"), nullable=False)
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    reussi: Mapped[bool] = mapped_column(Boolean, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    apprenant: Mapped["Apprenant"] = relationship(back_populates="quiz_attempts")  # type: ignore[name-defined]
    quiz: Mapped["Quiz"] = relationship(back_populates="attempts")  # type: ignore[name-defined]
