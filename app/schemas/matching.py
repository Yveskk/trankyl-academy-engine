from datetime import datetime

from pydantic import BaseModel


class MatchingRequestCreate(BaseModel):
    metier_code: str
    description: str | None = None


class MatchingRequestOut(BaseModel):
    id: int
    client_id: int
    metier_code: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class PrestataireMatchOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: str
    certifications: list[str] = []
    score: int = 0
    trust_score: float | None = None
    match_score: float | None = None
    match_breakdown: dict | None = None


class TrustScoreOut(BaseModel):
    apprenant_id: int
    score_pct: float
    rules_score: float
    rules_breakdown: dict
    llm_score: float | None
    justification: str
    computed_at: datetime


class VerificationUpdate(BaseModel):
    is_verified: bool | None = None
    reference_notes: str | None = None


class MatchOut(BaseModel):
    id: int
    request_id: int
    prestataire_id: int
    score: int
    created_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    receiver_id: int
    match_id: int | None = None
    content: str


class MessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    match_id: int | None
    content: str
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    other_user_id: int
    other_user_name: str
    last_message: str
    last_message_at: datetime
    unread_count: int


class ApprenantOut(BaseModel):
    id: int
    firstname: str
    lastname: str
    email: str
    phone: str | None
    created_at: datetime | None

    class Config:
        from_attributes = True


class ApprenantDetailOut(ApprenantOut):
    certifications: list[str] = []
    enrollment_count: int = 0
    completed_count: int = 0
    is_verified: bool = False
    trust_score: float | None = None


class ChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionDetailOut(ChatSessionOut):
    messages: list[ChatMessageOut] = []
