from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_apprenant
from app.db.session import get_db
from app.models.certification import Certification
from app.models.user import Apprenant
from app.schemas.certification import CertificationOut

router = APIRouter()


@router.get("/me", response_model=list[CertificationOut])
def my_certifications(current: Apprenant = Depends(get_current_apprenant), db: Session = Depends(get_db)):
    return db.query(Certification).filter(Certification.apprenant_id == current.id).all()
