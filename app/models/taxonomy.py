from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Metier(Base):
    """Un metier du referentiel (ex: babysitting, cuisine, nettoyage). Table
    `academy_metiers` (base partagee Trankyl) : chaque ligne reutilise
    directement l'id d'une sous-categorie de service reelle de Trankyl
    (`sub_categories.subcat_id`), puisque c'est elle qui relie deja les
    prestataires via `services.s_subcat_id`."""

    __tablename__ = "academy_metiers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), index=True, nullable=False)  # unique par pays (migration 0010)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="TG", server_default="TG")
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    nom_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    niveaux: Mapped[list["Niveau"]] = relationship(back_populates="metier", cascade="all, delete-orphan", order_by="Niveau.numero")


class Niveau(Base):
    """Un niveau de competence pour un metier donne. Table `academy_niveaux`."""

    __tablename__ = "academy_niveaux"
    __table_args__ = (UniqueConstraint("metier_id", "numero", name="uq_academy_niveau_metier_numero"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_metiers.id", ondelete="CASCADE"), nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    nom_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_debut: Mapped[date | None] = mapped_column(Date, nullable=True)

    metier: Mapped["Metier"] = relationship(back_populates="niveaux")
    competences: Mapped[list["Competence"]] = relationship(back_populates="niveau", cascade="all, delete-orphan", order_by="Competence.ordre")

    @property
    def certification_code(self) -> str:
        return f"{self.metier.code}_niveau_{self.numero}"


class Competence(Base):
    """Une competence concrete a l'interieur d'un niveau. Table
    `academy_competences`."""

    __tablename__ = "academy_competences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    niveau_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_niveaux.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    titre_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    niveau: Mapped["Niveau"] = relationship(back_populates="competences")
    modules: Mapped[list["Module"]] = relationship(back_populates="competence", cascade="all, delete-orphan", order_by="Module.ordre")  # type: ignore[name-defined]
