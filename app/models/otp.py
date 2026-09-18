from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OtpCode(Base):
    """Code a usage unique pour la reinitialisation de mot de passe. Table
    `academy_otp_codes` (base partagee Trankyl). Une ligne sert soit de
    code OTP (`purpose="password_reset"`), soit de jeton de
    reinitialisation emis apres verification (`purpose="reset_token"`,
    valeur dans `code`). Contrairement a l'ancienne table Academy, l'usage
    est marque par un booleen `used` (pas d'horodatage precis de
    consommation, l'info n'est pas necessaire)."""

    __tablename__ = "academy_otp_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), index=True, nullable=False)  # email du compte
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # apprenant | client | admin
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)  # password_reset | reset_token
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
