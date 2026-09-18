from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentSection(Base):
    """Bloc de texte editorial du site, identifie par une cle stable (ex:
    "home_careers"). Table `academy_content_sections` (base partagee
    Trankyl) : `key` est directement la cle primaire (pas de colonne `id`
    separee dans cette table)."""

    __tablename__ = "academy_content_sections"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtitle_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
