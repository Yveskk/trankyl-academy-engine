from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MatchingRequest(Base):
    """Demande d'un client cherchant un prestataire pour un metier donne.
    Table `academy_matching_requests` (base partagee Trankyl)."""

    __tablename__ = "academy_matching_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False)
    metier_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    client: Mapped["Client"] = relationship()  # type: ignore[name-defined]
    matches: Mapped[list["Match"]] = relationship(back_populates="request", cascade="all, delete-orphan")


class Match(Base):
    """Resultat du matching : un prestataire correspondant a une demande.
    Table `academy_matches` — colonne physique `vendor_id`, mappee sur
    l'attribut Python `prestataire_id`."""

    __tablename__ = "academy_matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_matching_requests.id", ondelete="CASCADE"), nullable=False)
    prestataire_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    request: Mapped["MatchingRequest"] = relationship(back_populates="matches")
    prestataire: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]


class Message(Base):
    """Message entre deux utilisateurs (client-prestataire). Table
    `academy_messages`."""

    __tablename__ = "academy_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    receiver_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    match_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("academy_matches.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sender: Mapped["Apprenant"] = relationship(foreign_keys=[sender_id])  # type: ignore[name-defined]
    receiver: Mapped["Apprenant"] = relationship(foreign_keys=[receiver_id])  # type: ignore[name-defined]
