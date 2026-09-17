from datetime import date, datetime

from pydantic import BaseModel


class EnrollmentOut(BaseModel):
    id: int
    module_id: int
    statut: str
    started_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class NiveauEnrollmentOut(BaseModel):
    id: int
    niveau_id: int
    metier_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class NiveauEnrollmentMineOut(NiveauEnrollmentOut):
    niveau_nom: str
    niveau_nom_en: str | None = None
    niveau_numero: int
    date_debut: date | None
    metier_code: str
    metier_nom: str
    metier_nom_en: str | None = None


class NiveauEnrollmentAdminOut(BaseModel):
    id: int
    apprenant_id: int
    apprenant_nom: str
    apprenant_email: str
    niveau_id: int
    niveau_nom: str
    niveau_numero: int
    date_debut: date | None
    metier_id: int
    metier_code: str
    metier_nom: str
    created_at: datetime
