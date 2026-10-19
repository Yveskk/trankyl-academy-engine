from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Verification(Base):
    """Code a usage unique envoye par WhatsApp, SMS ou email (inscription,
    connexion, mot de passe oublie). Table `academy_verifications` (migration
    0006). Le code n'est JAMAIS stocke en clair : seulement son empreinte
    HMAC. `request_id` (UUID aleatoire) est la seule reference exposee au
    navigateur."""

    __tablename__ = "academy_verifications"
    __table_args__ = (
        Index("ix_academy_verifications_dest", "destination", "created_at"),
        Index("ix_academy_verifications_ip", "ip", "created_at"),
        Index("ix_academy_verifications_account", "role", "account_id", "purpose"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    send_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AccountSecurity(Base):
    """Etat de securite d'un compte (numero/email verifies, echecs, verrouillage).
    Table `academy_account_security` (migration 0006). Une ligne est creee a la
    demande : un compte existant sans ligne = jamais verifie, sans blocage."""

    __tablename__ = "academy_account_security"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lock_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TrustedDevice(Base):
    """Appareil reconnu apres une verification reussie (case "faire confiance a
    cet appareil"). Seule l'empreinte du jeton est stockee. Table
    `academy_trusted_devices` (migration 0006)."""

    __tablename__ = "academy_trusted_devices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SecurityEvent(Base):
    """Journal d'audit : connexions, codes envoyes/verifies, verrouillages.
    Table `academy_security_events` (migration 0006). Jamais de code ni de mot
    de passe dans `detail`."""

    __tablename__ = "academy_security_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(12), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
