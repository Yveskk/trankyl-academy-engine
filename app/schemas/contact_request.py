from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ContactRequestCreate(BaseModel):
    prestataire_id: int
    message: str | None = None


class ContactRequestOut(BaseModel):
    id: int
    client_id: int
    prestataire_id: int
    initial_message: str | None
    status: str
    created_at: datetime
    reviewed_at: datetime | None


class ContactRequestAdminOut(ContactRequestOut):
    client_nom: str
    client_email: str
    client_phone: str | None
    client_created_at: datetime | None
    client_total_requests: int

    prestataire_nom: str
    prestataire_email: str
    prestataire_phone: str | None
    prestataire_is_verified: bool
    prestataire_trust_score: float | None
    prestataire_certifications: list[str]
    prestataire_created_at: datetime | None

    message_count: int
    last_message_at: datetime | None


class ContactRequestClientOut(ContactRequestOut):
    prestataire_nom: str
    unread_count: int = 0
    last_message: str | None = None
    last_message_at: datetime | None = None


class ContactRequestPrestataireOut(ContactRequestOut):
    client_nom: str
    unread_count: int = 0
    last_message: str | None = None
    last_message_at: datetime | None = None


class ContactRequestReview(BaseModel):
    status: Literal["approved", "rejected"]


class ContactMessageCreate(BaseModel):
    content: str


class ContactMessageOut(BaseModel):
    id: int
    contact_request_id: int
    sender_role: str
    content: str
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True
