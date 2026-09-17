from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Client(Base):
    """Un foyer/particulier qui cherche un prestataire via l'assistant SITA
    (/matching/chat) — distinct des apprenants (qui suivent une formation
    pour DEVENIR prestataire). Table separee : ce ne sont pas les memes
    personnes ni le meme parcours, meme si les deux pourront un jour se
    rejoindre via un vendor_id Trankyl commun."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    firstname: Mapped[str] = mapped_column(String(255), nullable=False)
    lastname: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
