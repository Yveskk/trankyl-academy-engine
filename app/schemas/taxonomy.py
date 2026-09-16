from pydantic import BaseModel


class CompetenceCreate(BaseModel):
    code: str
    titre: str
    description: str | None = None
    ordre: int = 0


class CompetenceOut(CompetenceCreate):
    id: int
    niveau_id: int

    class Config:
        from_attributes = True


class NiveauCreate(BaseModel):
    numero: int
    nom: str
    description: str | None = None


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


class MetierOut(MetierCreate):
    id: int

    class Config:
        from_attributes = True


class MetierDetailOut(MetierOut):
    niveaux: list[NiveauOut] = []
