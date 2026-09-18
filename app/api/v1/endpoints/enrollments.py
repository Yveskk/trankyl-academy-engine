from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin, get_current_apprenant
from app.db.session import get_db
from app.models.curriculum import Module
from app.models.progress import Enrollment, NiveauEnrollment
from app.models.taxonomy import Niveau
from app.models.user import Apprenant
from app.schemas.progress import EnrollmentOut, NiveauEnrollmentAdminOut, NiveauEnrollmentMineOut, NiveauEnrollmentOut

router = APIRouter()


@router.get("/me", response_model=list[EnrollmentOut])
def my_enrollments(current: Apprenant = Depends(get_current_apprenant), db: Session = Depends(get_db)):
    return db.query(Enrollment).filter(Enrollment.apprenant_id == current.id).all()


@router.post("/{module_id}", response_model=EnrollmentOut, status_code=201)
def enroll(module_id: int, current: Apprenant = Depends(get_current_apprenant), db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.apprenant_id == current.id, Enrollment.module_id == module_id)
        .first()
    )
    if existing:
        return existing

    enrollment = Enrollment(apprenant_id=current.id, module_id=module_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


# --- Inscription a un niveau complet (cohorte avec date de debut) ---


@router.get("/niveaux/me", response_model=list[NiveauEnrollmentMineOut])
def my_niveau_enrollments(current: Apprenant = Depends(get_current_apprenant), db: Session = Depends(get_db)):
    rows = (
        db.query(NiveauEnrollment)
        .options(joinedload(NiveauEnrollment.niveau).joinedload(Niveau.metier))
        .filter(NiveauEnrollment.apprenant_id == current.id)
        .order_by(NiveauEnrollment.created_at.desc())
        .all()
    )
    return [
        NiveauEnrollmentMineOut(
            id=r.id,
            niveau_id=r.niveau_id,
            metier_id=r.metier_id,
            niveau_nom=r.niveau.nom,
            niveau_nom_en=r.niveau.nom_en,
            niveau_numero=r.niveau.numero,
            date_debut=r.niveau.date_debut,
            metier_code=r.niveau.metier.code,
            metier_nom=r.niveau.metier.nom,
            metier_nom_en=r.niveau.metier.nom_en,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get(
    "/niveaux",
    response_model=list[NiveauEnrollmentAdminOut],
    dependencies=[Depends(get_current_admin)],
)
def list_niveau_enrollments(db: Session = Depends(get_db)):
    """Liste des inscriptions a des niveaux, pour l'admin."""
    rows = (
        db.query(NiveauEnrollment)
        .options(
            joinedload(NiveauEnrollment.apprenant),
            joinedload(NiveauEnrollment.niveau).joinedload(Niveau.metier),
        )
        .order_by(NiveauEnrollment.created_at.desc())
        .all()
    )
    # Le vendor lie a l'inscription peut avoir ete supprime du marketplace
    # Trankyl independamment de l'Academy (compte ferme) : on ignore ces
    # lignes orphelines plutot que de planter l'affichage admin.
    return [
        NiveauEnrollmentAdminOut(
            id=r.id,
            apprenant_id=r.apprenant_id,
            apprenant_nom=f"{r.apprenant.firstname} {r.apprenant.lastname}",
            apprenant_email=r.apprenant.email,
            niveau_id=r.niveau_id,
            niveau_nom=r.niveau.nom,
            niveau_numero=r.niveau.numero,
            date_debut=r.niveau.date_debut,
            metier_id=r.metier_id,
            metier_code=r.niveau.metier.code,
            metier_nom=r.niveau.metier.nom,
            created_at=r.created_at,
        )
        for r in rows
        if r.apprenant is not None
    ]


@router.post("/niveaux/{niveau_id}", response_model=NiveauEnrollmentOut, status_code=201)
def enroll_niveau(niveau_id: int, current: Apprenant = Depends(get_current_apprenant), db: Session = Depends(get_db)):
    niveau = db.get(Niveau, niveau_id)
    if not niveau:
        raise HTTPException(status_code=404, detail="Niveau introuvable")

    existing = (
        db.query(NiveauEnrollment)
        .filter(NiveauEnrollment.apprenant_id == current.id, NiveauEnrollment.niveau_id == niveau_id)
        .first()
    )
    if existing:
        return existing

    enrollment = NiveauEnrollment(apprenant_id=current.id, niveau_id=niveau_id, metier_id=niveau.metier_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment
