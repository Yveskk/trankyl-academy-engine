import os
from dotenv import load_dotenv

# Charger le .env dans os.environ AVANT tout import
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings

tags_metadata = [
    {"name": "auth", "description": "Inscription/connexion apprenant, connexion admin."},
    {"name": "taxonomy", "description": "Metiers, niveaux, competences. Lecture publique, ecriture admin."},
    {"name": "curriculum", "description": "Modules de formation et quiz. Lecture publique, ecriture admin."},
    {"name": "enrollments", "description": "Inscription d'un apprenant a un module et suivi de sa progression."},
    {"name": "quizzes", "description": "Soumission des tentatives de quiz, corrigees automatiquement."},
    {"name": "certifications", "description": "Certifications obtenues par l'apprenant connecte."},
]

app = FastAPI(
    title="Trankyl Academy Engine",
    description=(
        "API de Trankyl Academy : taxonomie de competences, curriculum de micro-certification, "
        "progression et certifications des apprenants. Service independant de trankyl_backend_nodejs "
        "(pas de vendor_id ici pour le moment)."
    ),
    version="0.1.0",
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
