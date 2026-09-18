from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Certification(Base):
    """Certification obtenue par un apprenant pour un niveau d'un metier.
    Table `academy_certifications` (base partagee Trankyl)."""

    __tablename__ = "academy_certifications"
    __table_args__ = (UniqueConstraint("vendor_id", "niveau_id", name="uq_academy_certification_vendor_niveau"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    apprenant_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    niveau_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_niveaux.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    taxonomy_version: Mapped[int] = mapped_column(Integer, default=1)
    delivree_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    apprenant: Mapped["Apprenant"] = relationship(back_populates="certifications")  # type: ignore[name-defined]
    niveau: Mapped["Niveau"] = relationship()  # type: ignore[name-defined]
