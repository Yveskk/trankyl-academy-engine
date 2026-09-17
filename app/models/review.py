from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Review(Base):
    """Avis d'un client sur un prestataire (apprenant certifie) apres une
    mise en relation. Alimente le score de confiance du prestataire — voir
    app.services.trust_score."""

    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    prestataire_id: Mapped[int] = mapped_column(ForeignKey("apprenants.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    client: Mapped["Client"] = relationship()  # type: ignore[name-defined]
    prestataire: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
