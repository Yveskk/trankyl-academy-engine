from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TrustScore(Base):
    """Dernier score de confiance calcule pour un apprenant (mis en cache).
    Table `academy_trust_scores` (base partagee Trankyl)."""

    __tablename__ = "academy_trust_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    apprenant_id: Mapped[int] = mapped_column(
        "vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    rules_score: Mapped[float] = mapped_column(Float, nullable=False)
    rules_breakdown_json: Mapped[str] = mapped_column(Text, nullable=False)
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    apprenant: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
