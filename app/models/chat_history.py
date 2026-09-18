from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ChatSession(Base):
    """Une session de chat entre un CLIENT et SITA. Table
    `academy_chat_sessions` (base partagee Trankyl) — la colonne physique
    est `client_id`, mappee sur l'attribut Python `user_id` pour ne rien
    changer au reste du code."""

    __tablename__ = "academy_chat_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column("client_id", BigInteger, ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="Nouvelle conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["Client"] = relationship()  # type: ignore[name-defined]
    messages: Mapped[list["ChatMessageRecord"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="ChatMessageRecord.created_at")


class ChatMessageRecord(Base):
    """Un message dans une session de chat. Table `academy_chat_messages`."""

    __tablename__ = "academy_chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
