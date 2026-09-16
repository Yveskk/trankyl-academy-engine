from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Certification(Base):
    """Certification obtenue par un apprenant pour un niveau d'un metier
    (ex: nounou_niveau_2). C'est cette donnee qui, plus tard, alimentera
    le moteur de matching cote Trankyl - pas geree dans ce lot."""

    __tablename__ = "certifications"
    __table_args__ = (UniqueConstraint("apprenant_id", "niveau_id", name="uq_certification_apprenant_niveau"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    apprenant_id: Mapped[int] = mapped_column(ForeignKey("apprenants.id", ondelete="CASCADE"), nullable=False)
    niveau_id: Mapped[int] = mapped_column(ForeignKey("niveaux.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), index=True, nullable=False)  # ex: nounou_niveau_2
    taxonomy_version: Mapped[int] = mapped_column(Integer, default=1)
    delivree_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    apprenant: Mapped["Apprenant"] = relationship(back_populates="certifications")
    niveau: Mapped["Niveau"] = relationship()
