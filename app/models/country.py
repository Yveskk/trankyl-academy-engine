from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Country(Base):
    """Pays propose sur le site (bande verte, filtrage des prestataires), gere
    depuis l'admin. Table `academy_countries` (migration 0005). Distincte de
    la table `countries` du marketplace (liste mondiale, non modifiee ici) :
    `marketplace_country_id` fait le lien quand il existe."""

    __tablename__ = "academy_countries"
    __table_args__ = (Index("ix_academy_countries_active", "is_active", "sort_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)  # ISO 3166-1 alpha-2 : TG, BJ, CI...
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    marketplace_country_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    calling_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    payment_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_text_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    help_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
