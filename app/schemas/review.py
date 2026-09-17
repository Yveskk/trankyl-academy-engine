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
