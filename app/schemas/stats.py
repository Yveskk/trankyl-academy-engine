from pydantic import BaseModel


class MetierStat(BaseModel):
    metier_code: str
    metier_nom: str
    metier_nom_en: str | None
    certified_count: int


class NiveauStat(BaseModel):
    metier_code: str
    metier_nom: str
    niveau_numero: int
    certifications_count: int


class GenreStat(BaseModel):
    genre: str
    count: int


class PublicImpactStats(BaseModel):
    # --- Formation ---
    total_apprenants: int
    total_reservations: int
    total_modules_completed: int
    total_certifications: int
    certifications_par_niveau: list[NiveauStat]
    repartition_par_metier: list[MetierStat]
    taux_completion_moyen_pct: float | None

    # --- Confiance & securite ---
    profils_verifies: int
    score_confiance_moyen: float | None
    pct_profils_bloques_verification: float | None

    # --- Portee ---
    nombre_villes: int
    repartition_genre: list[GenreStat]
