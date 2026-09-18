from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Review(Base):
    """Avis d'un client sur un prestataire (apprenant certifie). Table
    `academy_reviews` (base partagee Trankyl)."""

    __tablename__ = "academy_reviews"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_academy_review_rating_range"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False)
    prestataire_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    client: Mapped["Client"] = relationship()  # type: ignore[name-defined]
    prestataire: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
