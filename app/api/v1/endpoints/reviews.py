"""Avis clients sur les prestataires, apres une mise en relation. Public en
lecture (transparence), ecriture reservee aux clients connectes. Recalcule
automatiquement le score de confiance du prestataire concerne — voir
app.services.trust_score."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_client, get_admin_ctx, require_access
from app.db.session import get_db
from app.models.client import Client
from app.models.review import Review
from app.models.user import Apprenant
from app.schemas.review import ImportResult, ReviewAdminOut, ReviewCreate, ReviewModeration, ReviewOut, ReviewSummaryOut
from app.api.v1.endpoints.directory import clear_directory_cache
from app.services.countries import provider_in_country as vendor_in_country, provider_offer_clause as vendor_country_clause
from app.services.home import invalidate_home_cache
from app.services.trust_score import compute_trust_score

router = APIRouter()


@router.get("/prestataire/{prestataire_id}", response_model=ReviewSummaryOut)
def get_prestataire_reviews(prestataire_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(Review)
        .options(joinedload(Review.client))
        .filter(Review.prestataire_id == prestataire_id, Review.status == "approved")
        .order_by(Review.created_at.desc())
        .all()
    )
    # Le client peut avoir ete supprime du marketplace Trankyl depuis
    # (compte ferme) : on ignore ces avis orphelins plutot que de planter
    # l'affichage.
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
        if r.client is not None
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


# ---------------------------------------------------------------------------
# Administration : moderation + import des notes de reservations
# ---------------------------------------------------------------------------
def _admin_reviews(db: Session, country: str, status: str | None, limit: int) -> list[ReviewAdminOut]:
    clause, cparams = vendor_country_clause(db, country, "v")
    sql = (
        "SELECT r.id, r.vendor_id, v.vendor_name, r.client_id, c.client_name, r.rating, r.comment, r.status, r.source, "
        "r.booking_id, r.reply, r.replied_at, r.created_at FROM academy_reviews r "
        "JOIN vendors v ON v.vendor_id=r.vendor_id JOIN clients c ON c.client_id=r.client_id "
        f"WHERE (:status IS NULL OR r.status=:status) AND {clause} ORDER BY r.created_at DESC, r.id DESC LIMIT :lim"
    )
    rows = db.execute(text(sql), {"status": status, "lim": min(limit, 500), **cparams}).fetchall()
    return [
        ReviewAdminOut(
            id=r[0], vendor_id=r[1], vendor_name=r[2], client_id=r[3], client_firstname=(r[4] or "").split(" ", 1)[0],
            rating=r[5], comment=r[6], status=r[7], source=r[8], booking_id=r[9], reply=r[10], replied_at=r[11], created_at=r[12],
        )
        for r in rows
    ]


@router.get("/admin", response_model=list[ReviewAdminOut])
def admin_list_reviews(status: str | None = None, limit: int = 100, admin=Depends(require_access("reviews", write="moderate")), db: Session = Depends(get_db)):
    return _admin_reviews(db, admin.country, status, limit)


@router.patch("/admin/{review_id}", response_model=ReviewAdminOut)
def admin_moderate_review(review_id: int, payload: ReviewModeration, admin=Depends(require_access("reviews", write="moderate")), db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review or not vendor_in_country(db, review.prestataire_id, admin.country):
        raise HTTPException(status_code=404, detail="Avis introuvable")
    if payload.status is not None:
        review.status = payload.status
    if payload.reply is not None:
        review.reply = payload.reply or None
        review.replied_at = datetime.utcnow() if payload.reply else None
    db.commit()
    invalidate_home_cache()
    clear_directory_cache()
    # Le score de confiance depend des avis approuves.
    prestataire = db.get(Apprenant, review.prestataire_id)
    if prestataire:
        compute_trust_score(db, prestataire)
    return admin_list_reviews_one(db, admin.country, review_id)


def admin_list_reviews_one(db: Session, country: str, review_id: int) -> ReviewAdminOut:
    rows = [r for r in _admin_reviews(db, country, None, 500) if r.id == review_id]
    return rows[0]


@router.post("/admin/import-booking-marks", response_model=ImportResult)
def admin_import_booking_marks(admin=Depends(require_access("reviews", write="moderate")), db: Session = Depends(get_db)):
    """Importe les notes laissees sur les reservations (`booking_marks`) dans
    `academy_reviews`, en statut 'pending' pour moderation. Idempotent :
    l'unicite (source, booking_id) empeche tout doublon, on peut relancer
    sans risque. Les notes <= 0 (non renseignees) sont ignorees. Seules les reservations
    des prestataires du pays courant sont importees."""
    clause, cparams = vendor_country_clause(db, admin.country, "v")
    rows = db.execute(
        text(
            "SELECT bm.bk_mk_id, bm.bk_mk_booking_id, bm.bk_mk_value, bm.bk_mk_comment, bm.bk_mk_created_at, b.bk_vendor_id, b.bk_client_id "
            f"FROM booking_marks bm JOIN bookings b ON b.bk_id=bm.bk_mk_booking_id JOIN vendors v ON v.vendor_id=b.bk_vendor_id WHERE {clause}"
        ),
        cparams,
    ).fetchall()
    existing = {r[0] for r in db.execute(text("SELECT booking_id FROM academy_reviews WHERE source='booking_mark' AND booking_id IS NOT NULL"))}
    imported = skipped_existing = skipped_invalid = 0
    for mark_id, booking_id, value, comment, created, vendor_id, client_id in rows:
        rating = int(round(float(value or 0)))
        if not (1 <= rating <= 5) or not vendor_id or not client_id:
            skipped_invalid += 1
            continue
        if booking_id in existing:
            skipped_existing += 1
            continue
        db.add(Review(client_id=client_id, prestataire_id=vendor_id, rating=rating, comment=(comment or None), created_at=created or datetime.utcnow(),
                      booking_id=booking_id, status="pending", source="booking_mark"))
        existing.add(booking_id)
        imported += 1
    db.commit()
    return ImportResult(scanned=len(rows), imported=imported, skipped_existing=skipped_existing, skipped_invalid=skipped_invalid)
