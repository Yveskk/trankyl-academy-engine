from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentSection(Base):
    """Bloc de texte editorial du site, identifie par une cle stable (ex:
    "home_careers"). Table `academy_content_sections` (base partagee
    Trankyl) : `key` est directement la cle primaire (pas de colonne `id`
    separee dans cette table)."""

    __tablename__ = "academy_content_sections"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    # Pays du contenu (migration 0008) : cle primaire composee (key, country_code).
    country_code: Mapped[str] = mapped_column(String(2), primary_key=True, default="TG", server_default="TG")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtitle_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Configuration de la page d'accueil (migration 0002) : type de section,
    # ordre d'affichage et reglages libres (JSON) FR / EN.
    section_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    payload_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    payload_json_en: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
