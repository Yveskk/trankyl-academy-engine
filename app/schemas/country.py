from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CountryIn(BaseModel):
    code: str = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=100)
    marketplace_country_id: int | None = None
    calling_code: str | None = Field(default=None, max_length=8)
    currency_code: str | None = Field(default=None, max_length=8)
    payment_text: str | None = Field(default=None, max_length=255)
    payment_text_en: str | None = Field(default=None, max_length=255)
    help_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    is_default: bool = False
    sort_order: int | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha() or len(v) != 2:
            raise ValueError("Le code pays doit etre compose de 2 lettres (ex. TG, BJ, CI)")
        return v

    @field_validator("name", "name_en", "calling_code", "currency_code", "payment_text", "payment_text_en", "help_url")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("help_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("Le lien d'aide doit commencer par https://")
        return v


class CountryOut(BaseModel):
    id: int
    code: str
    name: str
    name_en: str | None
    marketplace_country_id: int | None
    marketplace_country_name: str | None = None
    calling_code: str | None
    currency_code: str | None
    payment_text: str | None
    payment_text_en: str | None
    help_url: str | None
    is_active: bool
    is_default: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CountryReorder(BaseModel):
    ids: list[int]


class MarketplaceCountry(BaseModel):
    id: int
    name: str
    code: str
    calling_code: str | None
    has_service: bool
