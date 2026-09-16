from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.curriculum import Module
from app.models.taxonomy import Competence, Metier, Niveau
from app.schemas.taxonomy import (
    CompetenceCreate,
    CompetenceOut,
    MetierCreate,
    MetierDetailOut,
    MetierOut,
    MetierUpdate,
    NiveauCreate,
    NiveauOut,
    NiveauUpdate,
)

router = APIRouter()

# Charge toute la hierarchie (niveaux -> competences -> modules -> quiz) en une
# seule requete SQL, pour que le site n'ait plus besoin d'un aller-retour par
# competence (GET /curriculum/modules?competence_id=...) apres avoir recupere
# le metier : c'etait la cause principale de la lenteur au clic sur un metier.
_METIER_DETAIL_LOADER = joinedload(Metier.niveaux).joinedload(Niveau.competences).joinedload(Competence.modules).joinedload(Module.quiz)


# --- Lecture publique (site Academy, futur moteur de matching) ---


@router.get("/metiers", response_model=list[MetierOut])
def list_metiers(db: Session = Depends(get_db)):
    return db.query(Metier).filter(Metier.is_active.is_(True)).order_by(Metier.nom).all()


@router.get("/metiers/{code}", response_model=MetierDetailOut)
def get_metier(code: str, db: Session = Depends(get_db)):
    metier = (
        db.query(Metier)
        .options(_METIER_DETAIL_LOADER)
        .filter(Metier.code == code, Metier.is_active.is_(True))
        .first()
    )
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    return metier


# --- Lecture + ecriture reservees aux admins ---


@router.get("/admin/metiers", response_model=list[MetierOut], dependencies=[Depends(get_current_admin)])
def list_all_metiers(db: Session = Depends(get_db)):
    """Liste complete pour l'admin, y compris les metiers desactives."""
    return db.query(Metier).order_by(Metier.nom).all()


@router.get("/admin/metiers/{metier_id}", response_model=MetierDetailOut, dependencies=[Depends(get_current_admin)])
def get_metier_admin(metier_id: int, db: Session = Depends(get_db)):
    """Detail complet (niveaux + competences) pour l'admin, sans filtre is_active
    — contrairement a GET /metiers/{code} qui est public et masque les metiers
    desactives. Sans ca, rafraichir la page admin apres desactivation d'un
    metier echouait (404) en tentant de recharger son detail via la route
    publique."""
    metier = (
        db.query(Metier)
        .options(_METIER_DETAIL_LOADER)
        .filter(Metier.id == metier_id)
        .first()
    )
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    return metier


@router.post("/metiers", response_model=MetierOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_metier(payload: MetierCreate, db: Session = Depends(get_db)):
    if db.query(Metier).filter(Metier.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Ce code metier existe deja")
    metier = Metier(**payload.model_dump())
    db.add(metier)
    db.commit()
    db.refresh(metier)
    return metier


@router.put("/metiers/{metier_id}", response_model=MetierOut, dependencies=[Depends(get_current_admin)])
def update_metier(metier_id: int, payload: MetierUpdate, db: Session = Depends(get_db)):
    metier = db.get(Metier, metier_id)
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    conflict = db.query(Metier).filter(Metier.code == payload.code, Metier.id != metier_id).first()
    if conflict:
        raise HTTPException(status_code=400, detail="Ce code metier existe deja")
    metier.code = payload.code
    metier.nom = payload.nom
    metier.description = payload.description
    metier.is_active = payload.is_active
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


@router.put("/niveaux/{niveau_id}", response_model=NiveauOut, dependencies=[Depends(get_current_admin)])
def update_niveau(niveau_id: int, payload: NiveauUpdate, db: Session = Depends(get_db)):
    niveau = db.get(Niveau, niveau_id)
    if not niveau:
        raise HTTPException(status_code=404, detail="Niveau introuvable")
    niveau.numero = payload.numero
    niveau.nom = payload.nom
    niveau.description = payload.description
    niveau.date_debut = payload.date_debut
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


@router.delete("/niveaux/{niveau_id}", status_code=204, dependencies=[Depends(get_current_admin)])
def delete_niveau(niveau_id: int, db: Session = Depends(get_db)):
    niveau = db.get(Niveau, niveau_id)
    if not niveau:
        raise HTTPException(status_code=404, detail="Niveau introuvable")
    db.delete(niveau)
    db.commit()


@router.delete("/competences/{competence_id}", status_code=204, dependencies=[Depends(get_current_admin)])
def delete_competence(competence_id: int, db: Session = Depends(get_db)):
    competence = db.get(Competence, competence_id)
    if not competence:
        raise HTTPException(status_code=404, detail="Competence introuvable")
    db.delete(competence)
    db.commit()
