"""Score de matching pondere et explicable entre un besoin (metier demande)
et un apprenant/prestataire candidat. Distinct du score de confiance
(app.services.trust_score) : le score de confiance mesure "peut-on faire
confiance a cette personne", le score de matching mesure "correspond-elle a
CE besoin precis". Le second utilise le premier comme un de ses criteres.
"""
from sqlalchemy.orm import Session

from app.models.certification import Certification
from app.models.progress import Enrollment
from app.models.taxonomy import Metier, Niveau
from app.models.trust import TrustScore
from app.models.user import Apprenant

# --- Ponderations du score de matching (somme = 1.0), documentees --------
MATCH_WEIGHTS = {
    # part des niveaux du metier demande couverts par une certification
    "certification_coverage": 0.55,
    # score de confiance de l'apprenant (voir trust_score.py), normalise 0-1
    "trust_score": 0.30,
    # experience : modules termines au total, plafonnee (proxy simple faute
    # d'un historique de missions reelles pour le moment)
    "experience": 0.15,
}
assert abs(sum(MATCH_WEIGHTS.values()) - 1.0) < 1e-9, "MATCH_WEIGHTS doit sommer a 1.0"

# Au-dela de ce nombre de modules termines, l'experience compte comme
# maximale (evite qu'un profil tres actif ecrase indefiniment les autres
# criteres) :
EXPERIENCE_CAP_MODULES = 10


def compute_match_score(
    db: Session, apprenant: Apprenant, metier_code: str, trust: TrustScore | None
) -> dict:
    """Retourne {"score": 0-100, "breakdown": {critere: {...}}} — jamais une
    boite noire : chaque critere et son poids sont exposes."""
    niveau_ids = {
        row[0]
        for row in db.query(Niveau.id).join(Metier).filter(Metier.code == metier_code).all()
    }
    certified_ids = (
        {
            row[0]
            for row in db.query(Certification.niveau_id)
            .filter(Certification.apprenant_id == apprenant.id, Certification.niveau_id.in_(niveau_ids))
            .all()
        }
        if niveau_ids
        else set()
    )
    coverage_ratio = (len(certified_ids) / len(niveau_ids)) if niveau_ids else 0.0

    trust_ratio = (trust.score_pct / 100.0) if trust else 0.0

    completed_modules = (
        db.query(Enrollment).filter(Enrollment.apprenant_id == apprenant.id, Enrollment.statut == "termine").count()
    )
    experience_ratio = min(completed_modules / EXPERIENCE_CAP_MODULES, 1.0)

    breakdown = {
        "certification_coverage": {
            "label": f"Niveaux certifies pour ce metier",
            "value_pct": round(coverage_ratio * 100, 1),
            "weight": MATCH_WEIGHTS["certification_coverage"],
            "detail": f"{len(certified_ids)}/{len(niveau_ids)} niveau(x)" if niveau_ids else "metier sans niveau publie",
        },
        "trust_score": {
            "label": "Score de confiance",
            "value_pct": round(trust_ratio * 100, 1),
            "weight": MATCH_WEIGHTS["trust_score"],
            "detail": f"{trust.score_pct}/100" if trust else "non calcule",
        },
        "experience": {
            "label": "Experience (modules termines)",
            "value_pct": round(experience_ratio * 100, 1),
            "weight": MATCH_WEIGHTS["experience"],
            "detail": f"{completed_modules} module(s) termine(s) (plafond {EXPERIENCE_CAP_MODULES})",
        },
    }

    final_score = sum(breakdown[k]["value_pct"] / 100 * MATCH_WEIGHTS[k] for k in MATCH_WEIGHTS) * 100
    return {"score": round(final_score, 1), "breakdown": breakdown}
