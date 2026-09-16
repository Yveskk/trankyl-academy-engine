from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BlogArticle(Base):
    """Article de blog, gere depuis l'admin. is_active permet de depublier
    un article sans le supprimer (meme logique que ContentSection/Metier)."""

    __tablename__ = "blog_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    # Paragraphes separes par une ligne vide ("\n\n"), decoupes cote API.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    read_time: Mapped[str] = mapped_column(String(20), default="3 min")
    cover: Mapped[str] = mapped_column(String(10), default="green")  # "green" | "gold", utilise si pas d'image
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
