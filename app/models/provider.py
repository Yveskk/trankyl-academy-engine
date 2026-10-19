from datetime import datetime, time

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProviderProfile(Base):
    """Donnees de profil public d'un prestataire que `vendors` ne porte pas
    (temps de reponse, ponctualite, assurance, couverture, mise en avant...).
    Table `academy_provider_profiles` (migration 0003), 1 ligne par
    prestataire, creee a la demande : un prestataire sans ligne se comporte
    comme avant."""

    __tablename__ = "academy_provider_profiles"
    __table_args__ = (Index("ix_academy_provider_profiles_featured", "is_featured", "featured_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), unique=True, nullable=False)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    about_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    response_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    on_time_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    is_insured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_address_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # None = automatique (regle), 1 = force "Top prestataire", 0 = exclu
    top_override: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    featured_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    public_slug: Mapped[str | None] = mapped_column(String(150), unique=True, nullable=True)
    # Details de profil public (migration 0004)
    visit_fee: Mapped[int | None] = mapped_column(Integer, nullable=True)  # "Deplacement + diagnostic des X FCFA"
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    services_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    services_note_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProviderMedia(Base):
    """Realisation d'un prestataire (photo, video, avant/apres). Table
    `academy_provider_media` (migration 0003)."""

    __tablename__ = "academy_provider_media"
    __table_args__ = (Index("ix_academy_provider_media_vendor", "vendor_id", "is_active", "sort_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="photo", server_default="photo")  # photo | video | before_after
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    thumb_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProviderAvailability(Base):
    """Plage horaire hebdomadaire d'un prestataire. Table
    `academy_provider_availability` (migration 0003)."""

    __tablename__ = "academy_provider_availability"
    __table_args__ = (Index("ix_academy_provider_availability_vendor", "vendor_id", "weekday", "is_active"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = lundi ... 6 = dimanche
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
