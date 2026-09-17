from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OtpCode(Base):
    """Code a usage unique pour la reinitialisation de mot de passe (envoye
    par email via Mailjet et/ou par SMS via AfrikSMS — memes identifiants
    que trankyl_backend_nodejs). Une ligne sert soit de code OTP
    (`purpose="password_reset"`), soit de jeton de reinitialisation emis
    apres verification (`purpose="reset_token"`, valeur dans `code`)."""

    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), index=True, nullable=False)  # email du compte
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # apprenant | client | admin
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)  # password_reset | reset_token
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
