from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuoteRequest(Base):
    """Demande de devis adressee a un prestataire (formulaire « Demander un devis »).

    Le demandeur peut ne pas avoir de compte : ses coordonnees sont alors saisies dans le formulaire ; s'il est connecte
    client, elles viennent de son compte (`client_id` renseigne). L'administration repond depuis le menu « Devis » : la reponse
    part par e-mail au demandeur. Table `academy_quote_requests` (migration 0012)."""

    __tablename__ = "academy_quote_requests"
    __table_args__ = (Index("ix_academy_quote_requests_country_status", "country_code", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="TG", server_default="TG")
    vendor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    slot_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lang: Mapped[str] = mapped_column(String(2), nullable=False, default="fr", server_default="fr")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", server_default="new")  # new | answered
    reply_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
