"""Avis clients sur les prestataires, apres une mise en relation. Public en
lecture (transparence), ecriture reservee aux clients connectes. Recalcule
automatiquement le score de confiance du prestataire concerne — voir
app.services.trust_score."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_client
from app.db.session import get_db
from app.models.client import Client
from app.models.review import Review
from app.models.user import Apprenant
from app.schemas.review import ReviewCreate, ReviewOut, ReviewSummaryOut
from app.services.trust_score import compute_trust_score

router = APIRouter()


@router.get("/prestataire/{prestataire_id}", response_model=ReviewSummaryOut)
def get_prestataire_reviews(prestataire_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(Review)
        .options(joinedload(Review.client))
        .filter(Review.prestataire_id == prestataire_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    reviews = [
        ReviewOut(
            id=r.id,
            prestataire_id=r.prestataire_id,
            rating=r.rating,
            comment=r.comment,
            created_at=r.created_at,
            client_firstname=r.client.firstname,
        )
        for r in rows
    ]
    average = round(sum(r.rating for r in rows) / len(rows), 1) if rows else None
    return ReviewSummaryOut(average_rating=average, review_count=len(rows), reviews=reviews)


@router.post("", response_model=ReviewOut, status_code=201)
def create_review(
    payload: ReviewCreate,
    current: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    prestataire = db.get(Apprenant, payload.prestataire_id)
    if not prestataire:
        raise HTTPException(status_code=404, detail="Prestataire introuvable")

    review = Review(
        client_id=current.id,
        prestataire_id=payload.prestataire_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    # Le score de confiance du prestataire doit refleter le nouvel avis
    # immediatement (meme logique que apres une verification admin).
    compute_trust_score(db, prestataire)

    return ReviewOut(
        id=review.id,
        prestataire_id=review.prestataire_id,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at,
        client_firstname=current.firstname,
    )
