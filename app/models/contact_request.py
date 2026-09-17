from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ContactRequest(Base):
    """Demande d'un client pour contacter un prestataire. Passe par une
    validation admin avant que la messagerie ne s'ouvre entre les deux :
    client -> demande (pending) -> admin approuve/rejette -> si approuve,
    un fil de discussion (ContactMessage) s'ouvre entre le client et le
    prestataire. Un seul enregistrement par paire client/prestataire :
    reutilise pour les echanges suivants une fois approuve."""

    __tablename__ = "contact_requests"
    __table_args__ = (UniqueConstraint("client_id", "prestataire_id", name="uq_contact_request_client_prestataire"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    prestataire_id: Mapped[int] = mapped_column(ForeignKey("apprenants.id", ondelete="CASCADE"), nullable=False)
    initial_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client: Mapped["Client"] = relationship()  # type: ignore[name-defined]
    prestataire: Mapped["Apprenant"] = relationship()  # type: ignore[name-defined]
    messages: Mapped[list["ContactMessage"]] = relationship(
        back_populates="contact_request", cascade="all, delete-orphan", order_by="ContactMessage.created_at"
    )


class ContactMessage(Base):
    """Un message dans un fil client<->prestataire, actif seulement une fois
    le ContactRequest approuve par l'admin."""

    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_request_id: Mapped[int] = mapped_column(ForeignKey("contact_requests.id", ondelete="CASCADE"), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # client | prestataire
    content: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contact_request: Mapped["ContactRequest"] = relationship(back_populates="messages")
