from datetime import datetime

from pydantic import BaseModel


class ContentSectionOut(BaseModel):
    key: str
    title: str
    subtitle: str | None
    title_en: str | None = None
    subtitle_en: str | None = None
    is_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class ContentSectionUpsert(BaseModel):
    title: str
    subtitle: str | None = None
    title_en: str | None = None
    subtitle_en: str | None = None
    is_active: bool = True
