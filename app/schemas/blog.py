from datetime import date, datetime

from pydantic import BaseModel, field_validator


class BlogArticleBase(BaseModel):
    slug: str
    title: str
    excerpt: str
    category: str
    read_time: str = "3 min"
    cover: str = "green"
    cover_image_url: str | None = None
    published_at: date

    @field_validator("cover")
    @classmethod
    def validate_cover(cls, v: str) -> str:
        if v not in ("green", "gold"):
            raise ValueError('cover doit etre "green" ou "gold"')
        return v


class BlogArticleCreate(BlogArticleBase):
    content: list[str]


class BlogArticleUpdate(BlogArticleBase):
    content: list[str]
    is_active: bool = True


class BlogArticleOut(BlogArticleBase):
    id: int
    is_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class BlogArticleDetailOut(BlogArticleOut):
    content: list[str]
