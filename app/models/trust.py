from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TrustScore(Base):
    """Dernier score de confiance calcule pour un apprenant (mis en cache
    car l'analyse IA des references a un cout). Combine une composante
    "regles" (faits objectifs verifiables en base) et, si des references
    sont fournies, une composante "analyse LLM" des references — voir
    app.services.trust_score pour le detail et les ponderations."""

    __tablename__ = "trust_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    apprenant_id: Mapped[int] = mapped_column(
        ForeignKey("apprenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    rules_score: Mapped[float] = mapped_column(Float, nullable=False)
    rules_breakdown_json: Mapped[str] = mapped_column(Text, nullable=False)
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    apprenant: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
