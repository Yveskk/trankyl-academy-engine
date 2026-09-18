from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Banner(Base):
    """Image de la banniere/carrousel de la page d'accueil. Table
    `academy_banners` (base partagee Trankyl). Maximum 3 en base (impose
    cote API) : `ordre` (1, 2 ou 3) dit quelle slide du carrousel elle
    remplace."""

    __tablename__ = "academy_banners"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2 ou 3
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    image_url_mobile: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
