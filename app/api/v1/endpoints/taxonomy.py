from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.taxonomy import Competence, Metier, Niveau
from app.schemas.taxonomy import (
    CompetenceCreate,
    CompetenceOut,
    MetierCreate,
    MetierDetailOut,
    MetierOut,
    NiveauCreate,
    NiveauOut,
)

router = APIRouter()


# --- Lecture publique (site Academy, futur moteur de matching) ---


@router.get("/metiers", response_model=list[MetierOut])
def list_metiers(db: Session = Depends(get_db)):
    return db.query(Metier).order_by(Metier.nom).all()


@router.get("/metiers/{code}", response_model=MetierDetailOut)
def get_metier(code: str, db: Session = Depends(get_db)):
    metier = (
        db.query(Metier)
        .options(joinedload(Metier.niveaux).joinedload(Niveau.competences))
        .filter(Metier.code == code)
        .first()
    )
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    return metier


# --- Ecriture reservee aux admins ---


@router.post("/metiers", response_model=MetierOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_metier(payload: MetierCreate, db: Session = Depends(get_db)):
    if db.query(Metier).filter(Metier.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Ce code metier existe deja")
    metier = Metier(**payload.model_dump())
    db.add(metier)
    db.commit()
    db.refresh(metier)
    return metier


@router.post("/metiers/{metier_id}/niveaux", response_model=NiveauOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_niveau(metier_id: int, payload: NiveauCreate, db: Session = Depends(get_db)):
    metier = db.get(Metier, metier_id)
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    niveau = Niveau(metier_id=metier_id, **payload.model_dump())
    db.add(niveau)
    db.commit()
    db.refresh(niveau)
    return niveau


@router.post("/niveaux/{niveau_id}/competences", response_model=CompetenceOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_competence(niveau_id: int, payload: CompetenceCreate, db: Session = Depends(get_db)):
    niveau = db.get(Niveau, niveau_id)
    if not niveau:
        raise HTTPException(status_code=404, detail="Niveau introuvable")
    if db.query(Competence).filter(Competence.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Ce code competence existe deja")
    competence = Competence(niveau_id=niveau_id, **payload.model_dump())
    db.add(competence)
    db.commit()
    db.refresh(competence)
    return competence


@router.delete("/metiers/{metier_id}", status_code=204, dependencies=[Depends(get_current_admin)])
def delete_metier(metier_id: int, db: Session = Depends(get_db)):
    metier = db.get(Metier, metier_id)
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    db.delete(metier)
    db.commit()
