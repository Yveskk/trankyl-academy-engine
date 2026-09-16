from datetime import datetime

from pydantic import BaseModel


class CertificationOut(BaseModel):
    id: int
    niveau_id: int
    code: str
    taxonomy_version: int
    delivree_at: datetime

    class Config:
        from_attributes = True
