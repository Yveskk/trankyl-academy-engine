"""Statistiques publiques d'impact — page vitrine (ex: dossier UNICEF), sans
authentification. Toutes les requetes joignent explicitement sur `vendors`
pour ne jamais compter une ligne orpheline (un vendor supprime du
marketplace Trankyl apres avoir ete certifie par l'Academy)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.certification import Certification
from app.models.progress import Enrollment
from app.models.taxonomy import Metier, Niveau
from app.models.trust import TrustScore
from app.models.user import Apprenant
from app.schemas.stats import GenreStat, MetierStat, NiveauStat, PublicImpactStats

router = APIRouter()


@router.get("/public", response_model=PublicImpactStats)
def public_impact_stats(db: Session = Depends(get_db)):
    total_apprenants = db.query(Apprenant).filter(Apprenant.academy_status.isnot(None)).count()

    # `bookings` appartient au marketplace Trankyl (pas de modele SQLAlchemy
    # dedie ici) : nombre de reservations reelles non annulees honorees par
    # nos prestataires certifies — la meme definition que celle utilisee
    # pour le backfill des certifications (statut NULL/"0"/"1"/"2" = pas
    # annule, cf. booking.service.ts cote trankyl_backend_nodejs).
    total_reservations = db.execute(
        text(
            "SELECT COUNT(*) FROM bookings b JOIN vendors v ON b.bk_vendor_id = v.vendor_id "
            "WHERE v.vendor_academy_status = 'certified_provider' "
            "AND (b.bk_service_status IS NULL OR b.bk_service_status NOT IN ('3','4'))"
        )
    ).scalar()

    total_certifications = (
        db.query(func.count(Certification.id)).join(Apprenant, Certification.apprenant_id == Apprenant.id).scalar()
    )

    started = (
        db.query(func.count(Enrollment.id)).join(Apprenant, Enrollment.apprenant_id == Apprenant.id).scalar()
    )
    completed = (
        db.query(func.count(Enrollment.id))
        .join(Apprenant, Enrollment.apprenant_id == Apprenant.id)
        .filter(Enrollment.statut == "termine")
        .scalar()
    )
    taux_completion_moyen_pct = round((completed / started) * 100, 1) if started else None

    niveau_rows = (
        db.query(Metier.code, Metier.nom, Niveau.numero, func.count(Certification.id))
        .select_from(Certification)
        .join(Apprenant, Certification.apprenant_id == Apprenant.id)
        .join(Niveau, Certification.niveau_id == Niveau.id)
        .join(Metier, Niveau.metier_id == Metier.id)
        .group_by(Metier.id, Niveau.numero)
        .order_by(Metier.nom, Niveau.numero)
        .all()
    )
    certifications_par_niveau = [
        NiveauStat(metier_code=code, metier_nom=nom, niveau_numero=numero, certifications_count=count)
        for code, nom, numero, count in niveau_rows
    ]

    metier_rows = (
        db.query(Metier.code, Metier.nom, Metier.nom_en, func.count(func.distinct(Apprenant.id)))
        .select_from(Certification)
        .join(Apprenant, Certification.apprenant_id == Apprenant.id)
        .join(Niveau, Certification.niveau_id == Niveau.id)
        .join(Metier, Niveau.metier_id == Metier.id)
        .group_by(Metier.id)
        .order_by(func.count(func.distinct(Apprenant.id)).desc())
        .all()
    )
    repartition_par_metier = [
        MetierStat(metier_code=code, metier_nom=nom, metier_nom_en=nom_en, certified_count=count)
        for code, nom, nom_en, count in metier_rows
    ]

    profils_verifies = (
        db.query(Apprenant).filter(Apprenant.academy_status.isnot(None), Apprenant.is_verified.is_(True)).count()
    )

    score_confiance_moyen = (
        db.query(func.avg(TrustScore.score_pct)).join(Apprenant, TrustScore.apprenant_id == Apprenant.id).scalar()
    )
    score_confiance_moyen = round(float(score_confiance_moyen), 1) if score_confiance_moyen is not None else None

    total_certifies = db.query(Apprenant).filter(Apprenant.academy_status == "certified_provider").count()
    non_verifies_certifies = (
        db.query(Apprenant)
        .filter(Apprenant.academy_status == "certified_provider", Apprenant.is_verified.is_(False))
        .count()
    )
    pct_profils_bloques_verification = (
        round((non_verifies_certifies / total_certifies) * 100, 1) if total_certifies else None
    )

    nombre_villes = (
        db.query(func.count(func.distinct(Apprenant.address_city)))
        .filter(Apprenant.academy_status.isnot(None), Apprenant.address_city.isnot(None), Apprenant.address_city != "")
        .scalar()
    )

    genre_rows = (
        db.query(Apprenant.sex, func.count(Apprenant.id))
        .filter(Apprenant.academy_status.isnot(None), Apprenant.sex.isnot(None), Apprenant.sex != "")
        .group_by(Apprenant.sex)
        .all()
    )
    repartition_genre = [GenreStat(genre=sex, count=count) for sex, count in genre_rows]

    return PublicImpactStats(
        total_apprenants=total_apprenants,
        total_reservations=total_reservations or 0,
        total_modules_completed=completed,
        total_certifications=total_certifications,
        certifications_par_niveau=certifications_par_niveau,
        repartition_par_metier=repartition_par_metier,
        taux_completion_moyen_pct=taux_completion_moyen_pct,
        profils_verifies=profils_verifies,
        score_confiance_moyen=score_confiance_moyen,
        pct_profils_bloques_verification=pct_profils_bloques_verification,
        nombre_villes=nombre_villes or 0,
        repartition_genre=repartition_genre,
    )
