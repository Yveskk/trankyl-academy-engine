from datetime import datetime

from pydantic import BaseModel


class EnrollmentOut(BaseModel):
    id: int
    module_id: int
    statut: str
    started_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True
