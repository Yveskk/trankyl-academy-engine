from datetime import datetime

from pydantic import BaseModel, field_validator


class BannerCreate(BaseModel):
    ordre: int
    image_url: str
    # Variante mobile optionnelle, saisie manuellement par l'admin : si vide,
    # le site retombe sur image_url pour toutes les tailles d'ecran.
    image_url_mobile: str | None = None

    @field_validator("ordre")
    @classmethod
    def validate_ordre(cls, v: int) -> int:
        if v not in (1, 2, 3):
            raise ValueError("ordre doit etre 1, 2 ou 3")
        return v


class BannerUpdate(BannerCreate):
    is_active: bool = True


class BannerOut(BaseModel):
    id: int
    ordre: int
    image_url: str
    image_url_mobile: str | None
    is_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True
