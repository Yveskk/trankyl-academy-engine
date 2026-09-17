from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Banner(Base):
    """Image de la banniere/carrousel de la page d'accueil, geree depuis
    l'admin (upload Cloudinary). Maximum 3 en base (impose cote API) :
    `ordre` (1, 2 ou 3) dit quelle slide du carrousel elle remplace. Une
    slide sans banniere active pour son `ordre` garde son image par defaut
    cote frontend (voir +page.ts) : on ne bloque jamais l'affichage."""

    __tablename__ = "banners"

    id: Mapped[int] = mapped_column(primary_key=True)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2 ou 3
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
