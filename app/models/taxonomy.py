from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Metier(Base):
    """Un metier du referentiel (ex: nounou, aide a domicile, cuisinier)."""

    __tablename__ = "metiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    niveaux: Mapped[list["Niveau"]] = relationship(back_populates="metier", cascade="all, delete-orphan", order_by="Niveau.numero")


class Niveau(Base):
    """Un niveau de competence pour un metier donne (1 = bases, 2 = intermediaire, ...)."""

    __tablename__ = "niveaux"
    __table_args__ = (UniqueConstraint("metier_id", "numero", name="uq_niveau_metier_numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    metier_id: Mapped[int] = mapped_column(ForeignKey("metiers.id", ondelete="CASCADE"), nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_debut: Mapped[date | None] = mapped_column(Date, nullable=True)

    metier: Mapped["Metier"] = relationship(back_populates="niveaux")
    competences: Mapped[list["Competence"]] = relationship(back_populates="niveau", cascade="all, delete-orphan", order_by="Competence.ordre")

    @property
    def certification_code(self) -> str:
        return f"{self.metier.code}_niveau_{self.numero}"


class Competence(Base):
    """Une competence concrete a l'interieur d'un niveau (ex: hygiene et
    lavage des mains). Se traduit ensuite en un ou plusieurs modules."""

    __tablename__ = "competences"

    id: Mapped[int] = mapped_column(primary_key=True)
    niveau_id: Mapped[int] = mapped_column(ForeignKey("niveaux.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    niveau: Mapped["Niveau"] = relationship(back_populates="competences")
    modules: Mapped[list["Module"]] = relationship(back_populates="competence", cascade="all, delete-orphan", order_by="Module.ordre")
