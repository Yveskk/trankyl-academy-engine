from datetime import date

from pydantic import BaseModel

from app.schemas.curriculum import ModuleOut


class CompetenceCreate(BaseModel):
    code: str
    titre: str
    description: str | None = None
    titre_en: str | None = None
    description_en: str | None = None
    ordre: int = 0


class CompetenceOut(CompetenceCreate):
    id: int
    niveau_id: int
    modules: list[ModuleOut] = []

    class Config:
        from_attributes = True


class NiveauCreate(BaseModel):
    numero: int
    nom: str
    description: str | None = None
    nom_en: str | None = None
    description_en: str | None = None
    date_debut: date | None = None


class NiveauUpdate(NiveauCreate):
    pass


class NiveauOut(NiveauCreate):
    id: int
    metier_id: int
    competences: list[CompetenceOut] = []

    class Config:
        from_attributes = True


class MetierCreate(BaseModel):
    code: str
    nom: str
    description: str | None = None
    nom_en: str | None = None
    description_en: str | None = None


class MetierUpdate(MetierCreate):
    is_active: bool = True


class MetierOut(MetierCreate):
    id: int
    is_active: bool

    class Config:
        from_attributes = True


class MetierDetailOut(MetierOut):
    niveaux: list[NiveauOut] = []
