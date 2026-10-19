from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import current_country, require_access
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


def _own_metier(db: Session, metier_id: int, country: str) -> Metier:
    """Un metier (et tout ce qu'il contient) n'existe que dans son pays."""
    metier = db.get(Metier, metier_id)
    if not metier or metier.country_code != country:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    return metier


def _own_niveau(db: Session, niveau_id: int, country: str) -> Niveau:
    niveau = db.get(Niveau, niveau_id)
    if not niveau or niveau.metier.country_code != country:
        raise HTTPException(status_code=404, detail="Niveau introuvable")
    return niveau


# --- Lecture publique (site Academy, futur moteur de matching) ---


@router.get("/metiers", response_model=list[MetierOut])
def list_metiers(country: str = Depends(current_country), db: Session = Depends(get_db)):
    return db.query(Metier).filter(Metier.is_active.is_(True), Metier.country_code == country).order_by(Metier.nom).all()


@router.get("/metiers/{code}", response_model=MetierDetailOut)
def get_metier(code: str, country: str = Depends(current_country), db: Session = Depends(get_db)):
    metier = (
        db.query(Metier)
        .options(_METIER_DETAIL_LOADER)
        .filter(Metier.code == code, Metier.is_active.is_(True), Metier.country_code == country)
        .first()
    )
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    return metier


# --- Lecture + ecriture reservees aux admins ---


@router.get("/admin/metiers", response_model=list[MetierOut])
def list_all_metiers(admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    """Liste complete du pays courant pour l'admin, y compris les metiers desactives."""
    return db.query(Metier).filter(Metier.country_code == admin.country).order_by(Metier.nom).all()


@router.get("/admin/metiers/{metier_id}", response_model=MetierDetailOut)
def get_metier_admin(metier_id: int, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    """Detail complet (niveaux + competences) pour l'admin, sans filtre is_active
    — contrairement a GET /metiers/{code} qui est public et masque les metiers
    desactives. Sans ca, rafraichir la page admin apres desactivation d'un
    metier echouait (404) en tentant de recharger son detail via la route
    publique."""
    metier = (
        db.query(Metier)
        .options(_METIER_DETAIL_LOADER)
        .filter(Metier.id == metier_id, Metier.country_code == admin.country)
        .first()
    )
    if not metier:
        raise HTTPException(status_code=404, detail="Metier introuvable")
    return metier


@router.post("/metiers", response_model=MetierOut, status_code=201)
def create_metier(payload: MetierCreate, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    if db.query(Metier).filter(Metier.code == payload.code, Metier.country_code == admin.country).first():
        raise HTTPException(status_code=400, detail="Ce code metier existe deja dans ce pays")
    metier = Metier(**payload.model_dump(), country_code=admin.country)
    db.add(metier)
    db.commit()
    db.refresh(metier)
    return metier


@router.put("/metiers/{metier_id}", response_model=MetierOut)
def update_metier(metier_id: int, payload: MetierUpdate, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    metier = _own_metier(db, metier_id, admin.country)
    conflict = db.query(Metier).filter(Metier.code == payload.code, Metier.id != metier_id, Metier.country_code == admin.country).first()
    if conflict:
        raise HTTPException(status_code=400, detail="Ce code metier existe deja dans ce pays")
    metier.code = payload.code
    metier.nom = payload.nom
    metier.description = payload.description
    metier.nom_en = payload.nom_en
    metier.description_en = payload.description_en
    metier.is_active = payload.is_active
    db.commit()
    db.refresh(metier)
    return metier


@router.post("/metiers/{metier_id}/niveaux", response_model=NiveauOut, status_code=201)
def create_niveau(metier_id: int, payload: NiveauCreate, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    _own_metier(db, metier_id, admin.country)
    niveau = Niveau(metier_id=metier_id, **payload.model_dump())
    db.add(niveau)
    db.commit()
    db.refresh(niveau)
    return niveau


@router.put("/niveaux/{niveau_id}", response_model=NiveauOut)
def update_niveau(niveau_id: int, payload: NiveauUpdate, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    niveau = _own_niveau(db, niveau_id, admin.country)
    niveau.numero = payload.numero
    niveau.nom = payload.nom
    niveau.description = payload.description
    niveau.nom_en = payload.nom_en
    niveau.description_en = payload.description_en
    niveau.date_debut = payload.date_debut
    db.commit()
    db.refresh(niveau)
    return niveau


@router.post("/niveaux/{niveau_id}/competences", response_model=CompetenceOut, status_code=201)
def create_competence(niveau_id: int, payload: CompetenceCreate, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    _own_niveau(db, niveau_id, admin.country)
    if db.query(Competence).filter(Competence.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Ce code competence existe deja")
    competence = Competence(niveau_id=niveau_id, **payload.model_dump())
    db.add(competence)
    db.commit()
    db.refresh(competence)
    return competence


@router.delete("/metiers/{metier_id}", status_code=204)
def delete_metier(metier_id: int, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    metier = _own_metier(db, metier_id, admin.country)
    db.delete(metier)
    db.commit()


@router.delete("/niveaux/{niveau_id}", status_code=204)
def delete_niveau(niveau_id: int, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    niveau = _own_niveau(db, niveau_id, admin.country)
    db.delete(niveau)
    db.commit()


@router.delete("/competences/{competence_id}", status_code=204)
def delete_competence(competence_id: int, admin=Depends(require_access("taxonomy")), db: Session = Depends(get_db)):
    competence = db.get(Competence, competence_id)
    if not competence or competence.niveau.metier.country_code != admin.country:
        raise HTTPException(status_code=404, detail="Competence introuvable")
    db.delete(competence)
    db.commit()
