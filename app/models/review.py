from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Review(Base):
    """Avis d'un client sur un prestataire (apprenant certifie). Table
    `academy_reviews` (base partagee Trankyl)."""

    __tablename__ = "academy_reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_academy_review_rating_range"),
        UniqueConstraint("source", "booking_id", name="uq_academy_reviews_source_booking"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False)
    prestataire_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Moderation + reponse du prestataire (migration 0003). Les avis
    # anterieurs sont 'approved' / source 'academy' (valeurs par defaut).
    booking_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="approved", server_default="approved")  # approved | pending | rejected
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    criteria_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="academy", server_default="academy")  # academy | booking_mark | admin

    client: Mapped["Client"] = relationship()  # type: ignore[name-defined]
    prestataire: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
