from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_apprenant
from app.db.session import get_db
from app.models.curriculum import Module
from app.models.progress import Enrollment
from app.models.user import Apprenant
from app.schemas.progress import EnrollmentOut

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
