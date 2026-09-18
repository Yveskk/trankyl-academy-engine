from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ContactRequest(Base):
    """Demande d'un client pour contacter un prestataire, moderee par un
    admin. Table `academy_contact_requests` (base partagee Trankyl)."""

    __tablename__ = "academy_contact_requests"
    __table_args__ = (UniqueConstraint("client_id", "vendor_id", name="uq_academy_contact_request_client_vendor"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False)
    prestataire_id: Mapped[int] = mapped_column("vendor_id", BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
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
    """Un message dans un fil client<->prestataire. Table
    `academy_contact_messages`."""

    __tablename__ = "academy_contact_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contact_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_contact_requests.id", ondelete="CASCADE"), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # client | prestataire
    content: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contact_request: Mapped["ContactRequest"] = relationship(back_populates="messages")
