from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BlogArticle(Base):
    """Article de blog = evenement reel Trankyl. Table `events` (base
    partagee Trankyl) : Academy et le site principal Trankyl partagent le
    meme flux d'actualites plutot que d'avoir chacun sa propre table de
    blog. Contrairement a l'ancienne table Academy, `events` n'a aucune
    colonne de traduction anglaise ni de slug — l'URL utilise directement
    `event_id`."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column("event_id", BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column("event_title", String(255), nullable=True)
    excerpt: Mapped[str | None] = mapped_column("event_description", Text, nullable=True)
    content: Mapped[str | None] = mapped_column("event_content", Text, nullable=True)
    category: Mapped[str | None] = mapped_column("event_category", String(191), nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column("event_image", String(255), nullable=True)
    event_start_date: Mapped[date | None] = mapped_column("event_start_date", Date, nullable=True)
    event_end_date: Mapped[date | None] = mapped_column("event_end_date", Date, nullable=True)
    is_active: Mapped[bool | None] = mapped_column("event_is_active", Boolean, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("event_created_at", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("event_updated_at", DateTime, nullable=True)

    @property
    def published_at(self) -> date | None:
        return self.created_at.date() if self.created_at else self.event_start_date
