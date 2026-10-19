from datetime import time

from pydantic import BaseModel, Field


class ProviderProfileIn(BaseModel):
    headline: str | None = Field(default=None, max_length=255)
    about: str | None = None
    about_en: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=500)
    response_time_minutes: int | None = Field(default=None, ge=0, le=100000)
    on_time_rate: float | None = Field(default=None, ge=0, le=100)
    is_insured: bool = False
    is_address_verified: bool = False
    top_override: int | None = Field(default=None, ge=0, le=1)
    is_featured: bool = False
    featured_order: int = 0
    public_slug: str | None = Field(default=None, max_length=150, pattern="^[a-z0-9][a-z0-9-]*$")
    visit_fee: int | None = Field(default=None, ge=0)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    service_radius_km: int | None = Field(default=None, ge=0, le=500)
    zone_label: str | None = Field(default=None, max_length=255)
    services_note: str | None = None
    services_note_en: str | None = None


class ProviderProfileOut(ProviderProfileIn):
    vendor_id: int
    persisted: bool


class MediaIn(BaseModel):
    kind: str = Field(default="photo", pattern="^(photo|video|before_after)$")
    url: str = Field(max_length=500)
    thumb_url: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=255)
    sort_order: int = 0
    is_active: bool = True


class MediaOut(MediaIn):
    id: int
    vendor_id: int


class AvailabilitySlot(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    is_active: bool = True


class ProviderListItem(BaseModel):
    vendor_id: int
    name: str
    city: str | None
    is_verified: bool
    academy_status: str | None
    is_featured: bool
    top_override: int | None
    is_insured: bool
