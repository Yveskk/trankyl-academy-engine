from datetime import date, datetime

from pydantic import BaseModel


class BlogArticleCreate(BaseModel):
    title: str
    excerpt: str
    category: str | None = None
    cover_image_url: str | None = None
    event_start_date: date | None = None
    event_end_date: date | None = None
    content: list[str]


class BlogArticleUpdate(BlogArticleCreate):
    is_active: bool = True


class BlogArticleOut(BaseModel):
    id: int
    # nullable cote base (table `events`, partagee avec le marketplace
    # Trankyl) : une ligne creee ailleurs pourrait ne pas avoir tous les
    # champs remplis.
    title: str | None
    excerpt: str | None
    category: str | None
    cover_image_url: str | None
    event_start_date: date | None
    event_end_date: date | None
    is_active: bool | None
    published_at: date | None
    updated_at: datetime | None

    class Config:
        from_attributes = True


class BlogArticleDetailOut(BlogArticleOut):
    content: list[str]
