from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HomeItemIn(BaseModel):
    kind: str | None = None
    sort_order: int = 0
    is_active: bool = True
    title: str | None = None
    title_en: str | None = None
    subtitle: str | None = None
    subtitle_en: str | None = None
    body: str | None = None
    body_en: str | None = None
    icon: str | None = None
    image_url: str | None = None
    tone: str | None = None
    link_url: str | None = None
    ref_type: str | None = Field(default=None, pattern="^(sub_category|vendor)$")
    ref_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HomeItemCreate(HomeItemIn):
    section_key: str


class HomeItemAdminOut(HomeItemIn):
    id: int | None = None
    section_key: str


class HomeSectionIn(BaseModel):
    title: str | None = None
    title_en: str | None = None
    subtitle: str | None = None
    subtitle_en: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_en: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    sort_order: int = 0


class HomeSectionAdminOut(HomeSectionIn):
    key: str
    type: str
    persisted: bool
    items_persisted: bool
    items: list[HomeItemAdminOut]


class ReorderIn(BaseModel):
    ids: list[int]


class SectionsOrderIn(BaseModel):
    keys: list[str]
