from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Banner(Base):
    """Image de la banniere/carrousel de la page d'accueil. Table
    `academy_banners` (base partagee Trankyl). `ordre` donne la position de
    la slide ; le nombre maximum est une constante cote API (MAX_BANNERS)."""

    __tablename__ = "academy_banners"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="TG", server_default="TG")
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)  # position (1 = premiere)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    image_url_mobile: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Contenu editorial optionnel (migration 0002).
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_label_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
