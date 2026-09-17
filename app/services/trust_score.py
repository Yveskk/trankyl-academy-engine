"""Score de confiance d'un apprenant/prestataire.

Combine deux composantes :
  1. Une composante "regles" : des faits objectifs, entierement verifiables
     en base (taux de certification, qualite des quiz, taux de completion,
     verification manuelle par un admin).
  2. Une composante "analyse IA des references" : si l'apprenant a fourni un
     texte de references/temoignages (`Apprenant.reference_notes`), SITA
     (Gemini) l'analyse et produit une note + une justification en francais.
     Sans reference fournie, le score final repose a 100% sur les regles —
     on ne fabrique jamais un avis IA a partir de rien.

Toutes les ponderations et le seuil de matching sont des constantes de ce
module (documentees ci-dessous) : c'est la source unique de verite pour le
README et pour l'audit.
"""
import json

from sqlalchemy.orm import Session

from app.models.certification import Certification
from app.models.progress import Enrollment, NiveauEnrollment, QuizAttempt
from app.models.review import Review
from app.models.trust import TrustScore
from app.models.user import Apprenant
from app.services.ai_matching import _get_client

# --- Composante "regles" (somme des poids = 1.0) --------------------------
RULES_WEIGHTS = {
    # part des niveaux inscrits (niveau_enrollments) effectivement certifies
    "certifications": 0.30,
    # moyenne des scores obtenus aux tentatives de quiz (0-100 -> 0-1)
    "quiz_quality": 0.20,
    # part des modules commences qui ont ete termines
    "completion_rate": 0.10,
    # compte verifie manuellement par un admin (identite / serieux) : 0 ou 1
    "account_verified": 0.15,
    # moyenne des avis clients (1-5 etoiles -> 0-100%) — 0% si aucun avis,
    # on ne fabrique jamais un signal positif a partir de l'absence de donnee
    "client_reviews": 0.25,
}
assert abs(sum(RULES_WEIGHTS.values()) - 1.0) < 1e-9, "RULES_WEIGHTS doit sommer a 1.0"

# --- Ponderation finale quand des references sont analysees par l'IA ------
RULES_WEIGHT_WITH_REFERENCES = 0.65
LLM_WEIGHT_WITH_REFERENCES = 0.35
assert abs(RULES_WEIGHT_WITH_REFERENCES + LLM_WEIGHT_WITH_REFERENCES - 1.0) < 1e-9

# --- Seuil de matching ------------------------------------------------------
# En plus d'etre verifie (Apprenant.is_verified), un apprenant doit avoir un
# score de confiance >= ce seuil pour apparaitre dans /prestataires ou dans
# les suggestions de SITA. Choisi pour exclure les profils sans aucun track
# record verifiable (score "regles seules" tres bas) sans etre punitif pour
# un profil recent mais deja verifie et avec de bons quiz.
TRUST_SCORE_THRESHOLD = 50.0


def _rules_component(db: Session, apprenant: Apprenant) -> tuple[float, dict]:
    """Calcule la composante "regles" (0-100) et son detail par critere."""
    breakdown: dict[str, dict] = {}

    # 1. Certifications : niveaux inscrits vs niveaux effectivement certifies
    enrolled_niveau_ids = {
        row[0]
        for row in db.query(NiveauEnrollment.niveau_id).filter(NiveauEnrollment.apprenant_id == apprenant.id).all()
    }
    certified_niveau_ids = {
        row[0]
        for row in db.query(Certification.niveau_id).filter(Certification.apprenant_id == apprenant.id).all()
    }
    if enrolled_niveau_ids:
        cert_ratio = len(certified_niveau_ids & enrolled_niveau_ids) / len(enrolled_niveau_ids)
    else:
        cert_ratio = 0.0
    breakdown["certifications"] = {
        "label": "Niveaux certifies parmi les niveaux suivis",
        "value_pct": round(cert_ratio * 100, 1),
        "weight": RULES_WEIGHTS["certifications"],
        "detail": f"{len(certified_niveau_ids & enrolled_niveau_ids)}/{len(enrolled_niveau_ids)} niveau(x)",
    }

    # 2. Qualite des quiz : moyenne des scores obtenus
    attempts = db.query(QuizAttempt.score_pct).filter(QuizAttempt.apprenant_id == apprenant.id).all()
    if attempts:
        quiz_ratio = min(sum(a[0] for a in attempts) / len(attempts) / 100.0, 1.0)
    else:
        quiz_ratio = 0.0
    breakdown["quiz_quality"] = {
        "label": "Moyenne des scores de quiz",
        "value_pct": round(quiz_ratio * 100, 1),
        "weight": RULES_WEIGHTS["quiz_quality"],
        "detail": f"{len(attempts)} tentative(s)" if attempts else "aucune tentative",
    }

    # 3. Taux de completion des modules commences
    total_enrollments = db.query(Enrollment).filter(Enrollment.apprenant_id == apprenant.id).count()
    completed_enrollments = (
        db.query(Enrollment).filter(Enrollment.apprenant_id == apprenant.id, Enrollment.statut == "termine").count()
    )
    completion_ratio = (completed_enrollments / total_enrollments) if total_enrollments else 0.0
    breakdown["completion_rate"] = {
        "label": "Modules termines parmi les modules commences",
        "value_pct": round(completion_ratio * 100, 1),
        "weight": RULES_WEIGHTS["completion_rate"],
        "detail": f"{completed_enrollments}/{total_enrollments} module(s)",
    }

    # 4. Verification manuelle par un admin
    verified_ratio = 1.0 if apprenant.is_verified else 0.0
    breakdown["account_verified"] = {
        "label": "Identite verifiee par un administrateur",
        "value_pct": round(verified_ratio * 100, 1),
        "weight": RULES_WEIGHTS["account_verified"],
        "detail": "verifie" if apprenant.is_verified else "non verifie",
    }

    # 5. Moyenne des avis clients (1-5 etoiles)
    ratings = [r[0] for r in db.query(Review.rating).filter(Review.prestataire_id == apprenant.id).all()]
    reviews_ratio = ((sum(ratings) / len(ratings)) / 5.0) if ratings else 0.0
    breakdown["client_reviews"] = {
        "label": "Moyenne des avis clients",
        "value_pct": round(reviews_ratio * 100, 1),
        "weight": RULES_WEIGHTS["client_reviews"],
        "detail": f"{len(ratings)} avis, moyenne {sum(ratings) / len(ratings):.1f}/5" if ratings else "aucun avis",
    }

    rules_score = sum(breakdown[k]["value_pct"] / 100 * RULES_WEIGHTS[k] for k in RULES_WEIGHTS) * 100
    return round(rules_score, 1), breakdown


def _llm_reference_component(apprenant: Apprenant, rules_breakdown: dict) -> tuple[float | None, str]:
    """Analyse les references/temoignages fournis avec Gemini. Retourne
    (None, motif) si aucune reference n'est disponible : on n'invente jamais
    un avis IA a partir de rien."""
    notes = (apprenant.reference_notes or "").strip()
    if not notes:
        return None, "Aucune reference fournie par l'apprenant — score base uniquement sur les criteres objectifs."

    client = _get_client()
    if client is None:
        return None, "Cle API Gemini absente : analyse des references indisponible pour le moment."

    prompt = f"""Tu evalues la fiabilite d'un(e) candidat(e) a partir de references/temoignages fournis.
Candidat(e) : {apprenant.firstname} {apprenant.lastname}
References/temoignages fournis par le candidat :
\"\"\"{notes}\"\"\"

Reponds STRICTEMENT en JSON, sans texte autour, avec ce format exact :
{{"score": <entier 0-100>, "justification": "<2-3 phrases en francais expliquant la note>"}}

Consignes de notation :
- 80-100 : references precises, verifiables, tres positives, plusieurs sources
- 50-79 : references positives mais generiques ou peu detaillees
- 20-49 : references vagues, incompletes ou peu convaincantes
- 0-19 : contenu suspect, incoherent ou clairement fabrique
Sois strict : un texte vague ou trop court ne merite pas un score eleve."""

    try:
        from google.genai import types

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            # gemini-3.6-flash consomme une partie du budget en tokens de
            # "raisonnement" interne avant de produire la reponse visible ;
            # un budget trop bas tronque le JSON avant la fin (vu en test :
            # ~380 tokens de "thoughts" pour ce prompt).
            config=types.GenerateContentConfig(max_output_tokens=1536),
        )
        raw = (response.text or "").strip()
        # Gemini renvoie parfois le JSON entoure de ```json ... ``` malgre la consigne.
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[4:] if raw.startswith("json") else raw
        data = json.loads(raw)
        score = max(0.0, min(100.0, float(data["score"])))
        justification = str(data["justification"]).strip()
        return round(score, 1), justification
    except Exception as e:
        print(f"[trust_score] Erreur analyse LLM des references: {e}")
        return None, f"Analyse IA des references indisponible (erreur technique : {e})."


def compute_trust_score(db: Session, apprenant: Apprenant) -> TrustScore:
    """Calcule (ou recalcule) le score de confiance d'un apprenant, le
    persiste (cache) et le retourne. Idempotent : peut etre rappele a tout
    moment (ex: apres verification admin ou ajout de references)."""
    rules_score, breakdown = _rules_component(db, apprenant)
    llm_score, llm_justification = _llm_reference_component(apprenant, breakdown)

    if llm_score is not None:
        final_score = rules_score * RULES_WEIGHT_WITH_REFERENCES + llm_score * LLM_WEIGHT_WITH_REFERENCES
    else:
        final_score = rules_score

    justification_parts = [
        f"Score regles ({rules_score}/100) : "
        + "; ".join(f"{v['label']} = {v['value_pct']}% (poids {int(v['weight'] * 100)}%)" for v in breakdown.values())
        + "."
    ]
    if llm_score is not None:
        justification_parts.append(f"Analyse IA des references ({llm_score}/100) : {llm_justification}")
    else:
        justification_parts.append(llm_justification)
    justification = " ".join(justification_parts)

    existing = db.query(TrustScore).filter(TrustScore.apprenant_id == apprenant.id).first()
    if existing:
        existing.score_pct = round(final_score, 1)
        existing.rules_score = rules_score
        existing.rules_breakdown_json = json.dumps(breakdown, ensure_ascii=False)
        existing.llm_score = llm_score
        existing.justification = justification
        record = existing
    else:
        record = TrustScore(
            apprenant_id=apprenant.id,
            score_pct=round(final_score, 1),
            rules_score=rules_score,
            rules_breakdown_json=json.dumps(breakdown, ensure_ascii=False),
            llm_score=llm_score,
            justification=justification,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return record


def is_matching_eligible(apprenant: Apprenant, trust: TrustScore | None) -> bool:
    """Blocage automatique : un apprenant n'est jamais propose par le
    matching (recherche publique ou SITA) s'il n'est pas verifie, ou si son
    score de confiance n'a pas ete calcule, ou est sous le seuil."""
    if not apprenant.is_verified:
        return False
    if trust is None:
        return False
    return trust.score_pct >= TRUST_SCORE_THRESHOLD
