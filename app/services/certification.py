from sqlalchemy.orm import Session

from app.models.certification import Certification
from app.models.curriculum import Module
from app.models.progress import Enrollment
from app.models.taxonomy import Competence, Niveau


def maybe_issue_certification(db: Session, apprenant_id: int, niveau_id: int) -> Certification | None:
    """Si l'apprenant a termine tous les modules de tous les competences
    d'un niveau, delivre la certification correspondante (ex: nounou_niveau_2).
    Idempotent : ne recree pas de certification si elle existe deja."""

    niveau = db.get(Niveau, niveau_id)
    if niveau is None:
        return None

    all_module_ids = [
        m.id
        for m in db.query(Module).join(Competence).filter(Competence.niveau_id == niveau_id).all()
    ]
    if not all_module_ids:
        return None

    completed_count = (
        db.query(Enrollment)
        .filter(
            Enrollment.apprenant_id == apprenant_id,
            Enrollment.module_id.in_(all_module_ids),
            Enrollment.statut == "termine",
        )
        .count()
    )
    if completed_count < len(all_module_ids):
        return None

    existing = (
        db.query(Certification)
        .filter(Certification.apprenant_id == apprenant_id, Certification.niveau_id == niveau_id)
        .first()
    )
    if existing:
        return existing

    certification = Certification(
        apprenant_id=apprenant_id,
        niveau_id=niveau_id,
        code=niveau.certification_code,
    )
    db.add(certification)
    db.commit()
    db.refresh(certification)
    return certification
