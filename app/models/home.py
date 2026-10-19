from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HomeItem(Base):
    """Carte repetable d'une section de la page d'accueil (service mis en
    avant, garantie, etape, puce de recherche, partenaire, temoignage manuel,
    carte d'application...). Table `academy_home_items` (migration 0002).

    `section_key` designe la section (cle de `academy_content_sections`).
    `ref_type`/`ref_id` permettent de pointer vers une donnee existante
    (sous-categorie Trankyl, prestataire...) dont le nom/l'image sont alors
    lus a la source, sans duplication ; `title`/`subtitle`... servent de
    surcharge ou de contenu libre. `data_json` : reglages propres au type
    d'item (ex. source d'un chiffre cle)."""

    __tablename__ = "academy_home_items"
    __table_args__ = (
        Index("ix_academy_home_items_section", "section_key", "is_active", "sort_order"),
        Index("ix_academy_home_items_ref", "ref_type", "ref_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="TG", server_default="TG")
    kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
