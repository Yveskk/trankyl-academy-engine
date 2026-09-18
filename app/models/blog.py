from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BlogArticle(Base):
    """Article de blog, gere depuis l'admin. Table `academy_blog_articles`
    (base partagee Trankyl)."""

    __tablename__ = "academy_blog_articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excerpt_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_time: Mapped[str] = mapped_column(String(20), default="3 min")
    cover: Mapped[str] = mapped_column(String(20), default="green")  # "green" | "gold"
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
