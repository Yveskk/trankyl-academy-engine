from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Enrollment(Base):
    """Inscription d'un apprenant a un module et suivi de sa progression."""

    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("apprenant_id", "module_id", name="uq_enrollment_apprenant_module"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    apprenant_id: Mapped[int] = mapped_column(ForeignKey("apprenants.id", ondelete="CASCADE"), nullable=False)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    statut: Mapped[str] = mapped_column(String(20), default="en_cours")  # en_cours | termine
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    apprenant: Mapped["Apprenant"] = relationship(back_populates="enrollments")
    module: Mapped["Module"] = relationship(back_populates="enrollments")


class NiveauEnrollment(Base):
    """Inscription d'un apprenant a un niveau complet (la cohorte qui demarre
    a sa date_debut), distincte de l'inscription a un module individuel.
    metier_id est denormalise (deduit de niveau.metier_id a la creation) pour
    que l'admin puisse filtrer/afficher par metier sans jointure."""

    __tablename__ = "niveau_enrollments"
    __table_args__ = (UniqueConstraint("apprenant_id", "niveau_id", name="uq_niveau_enrollment_apprenant_niveau"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    apprenant_id: Mapped[int] = mapped_column(ForeignKey("apprenants.id", ondelete="CASCADE"), nullable=False)
    niveau_id: Mapped[int] = mapped_column(ForeignKey("niveaux.id", ondelete="CASCADE"), nullable=False)
    metier_id: Mapped[int] = mapped_column(ForeignKey("metiers.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    apprenant: Mapped["Apprenant"] = relationship()
    niveau: Mapped["Niveau"] = relationship()
    metier: Mapped["Metier"] = relationship()


class QuizAttempt(Base):
    """Une tentative de quiz par un apprenant, corrigee automatiquement."""

    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    apprenant_id: Mapped[int] = mapped_column(ForeignKey("apprenants.id", ondelete="CASCADE"), nullable=False)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    reussi: Mapped[bool] = mapped_column(Boolean, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    apprenant: Mapped["Apprenant"] = relationship(back_populates="quiz_attempts")
    quiz: Mapped["Quiz"] = relationship(back_populates="attempts")
