from datetime import datetime

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    prestataire_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class ReviewOut(BaseModel):
    id: int
    prestataire_id: int
    rating: int
    comment: str | None
    created_at: datetime
    client_firstname: str

    class Config:
        from_attributes = True


class ReviewSummaryOut(BaseModel):
    average_rating: float | None
    review_count: int
    reviews: list[ReviewOut]


class ReviewAdminOut(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str | None = None
    client_id: int
    client_firstname: str | None = None
    rating: int
    comment: str | None
    status: str
    source: str
    booking_id: int | None
    reply: str | None
    replied_at: datetime | None
    created_at: datetime


class ReviewModeration(BaseModel):
    status: str | None = Field(default=None, pattern="^(approved|pending|rejected)$")
    reply: str | None = None


class ImportResult(BaseModel):
    scanned: int
    imported: int
    skipped_existing: int
    skipped_invalid: int
