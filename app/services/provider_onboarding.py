"""Parcours d'un prestataire apres l'inscription : profil -> formulaire d'enrolement -> tableau de bord.

Les etapes et les champs sont ceux de l'ancien site Trankyl (profil prestataire + formulaire d'enrolement), et les donnees
vivent dans les MEMES tables (`vendors`, `vendor_enrollments`) : l'admin Trankyl existant continue de tout voir.

Regles :
  * profil complet  = `vendor_if_prof_comp = '1'` (meme drapeau que le backend Trankyl) ;
  * enrolement      = brouillon (`draft`) tant qu'il n'est pas soumis ; soumis -> `pending` ; l'equipe l'approuve ou le refuse ;
  * tableau de bord = profil complet ET enrolement soumis (en attente ou approuve) avec toutes les donnees importantes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

ID_TYPES = {"CNI": True, "CARTE_ELECTEUR": True, "PERMIS": True, "PASSEPORT": False}  # type -> verso requis
SECTORS = {"btp", "transport", "maison", "jardinage", "informatique", "beaute", "sante", "education", "restauration", "autre"}
LEGAL_FORMS = {"auto_entrepreneur", "micro_entreprise", "sarl", "sa", "sas", "ei", "autre"}
STUDY_LEVELS = {"aucun", "primaire", "college", "lycee", "bts", "licence", "master", "doctorat", "formation", "autre"}
LANGUAGES = ["Français", "Anglais", "Portugais", "Langue locale", "Autre"]

# cle -> libelle : les memes libelles que l'admin Trankyl (checklist de validation de l'administration).
FIELD_LABELS = {
    "is_professional": "Statut", "is_expert": "Expert", "if_company": "Entreprise", "company_name": "Nom entreprise",
    "company_sector": "Secteur d'activité", "company_type": "Forme juridique", "study_level": "Niveau d'études", "languages": "Langues",
    "custom_language": "Autre langue", "id_type": "Type de pièce", "id_file": "Pièce d'identité (recto)", "id_file_verso": "Pièce d'identité (verso)",
    "rc_file": "Registre de Commerce", "casier_file": "Casier judiciaire", "cef_files": "Cartes CEF", "diploma_files": "Diplômes / Certifications",
    "cv_files": "Curriculum Vitae (CV)",
}


def jlist(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        v = json.loads(raw)
        return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    except (TypeError, ValueError):
        return [str(raw)]


# --------------------------------------------------------------------------- profil
PROFILE_COLS = (
    "vendor_id, vendor_name, vendor_family_name, vendor_email, vendor_phone, vendor_sex, vendor_dob, vendor_address, vendor_address_city, vendor_address_country, "
    "vendor_street_number, vendor_street_name, vendor_postal_code, vendor_latitude, vendor_longitude, vendor_geolocation, vendor_bio, vendor_if_company, "
    "vendor_currency_id, vendor_working_district, vendor_image, vendor_if_prof_comp, vendor_country_code, vendor_country_id, vendor_academy_status, "
    "vendor_academy_verified, vendor_training_completed, vendor_interview_done, company_name"
)


def vendor_row(db: Session, vendor_id: int) -> dict | None:
    db.rollback()
    r = db.execute(text(f"SELECT {PROFILE_COLS} FROM vendors WHERE vendor_id=:i"), {"i": vendor_id}).mappings().first()
    return dict(r) if r else None


def profile_missing(v: dict, have_currencies: bool) -> list[str]:
    """Champs obligatoires du profil (ceux de l'ancien site) qui manquent encore."""
    need = {
        "fname": v.get("vendor_name"), "family_name": v.get("vendor_family_name"), "email": v.get("vendor_email"), "sex": v.get("vendor_sex"),
        "dob": v.get("vendor_dob"), "vendor_address_country": v.get("vendor_address_country"), "vendor_address_city": v.get("vendor_address_city"),
    }
    if have_currencies:
        need["vendor_currency"] = v.get("vendor_currency_id")
    has_pin = v.get("vendor_latitude") is not None and v.get("vendor_longitude") is not None
    if not has_pin:
        need["address"] = v.get("vendor_address")
    return [k for k, val in need.items() if val in (None, "", 0, "null")]


def profile_complete(v: dict) -> bool:
    return str(v.get("vendor_if_prof_comp")) == "1"


def have_currencies(db: Session) -> bool:
    try:
        return (db.execute(text("SELECT COUNT(*) FROM currencies")).scalar() or 0) > 0
    except Exception:  # noqa: BLE001  (table absente d'une base ancienne)
        db.rollback()
        return False


# --------------------------------------------------------------------------- enrolement
def enrollment_row(db: Session, vendor_id: int) -> dict | None:
    db.rollback()
    r = db.execute(text("SELECT * FROM vendor_enrollments WHERE enroll_vendor_id=:i ORDER BY enroll_id DESC LIMIT 1"), {"i": vendor_id}).mappings().first()
    return dict(r) if r else None


def enrollment_missing(e: dict | None) -> list[dict]:
    """Donnees importantes du dossier qui manquent (cle + libelle). Vide = dossier complet."""
    e = e or {}
    out: list[str] = []
    if not e.get("enroll_study_level"):
        out.append("study_level")
    if not e.get("enroll_languages"):
        out.append("languages")
    if (e.get("enroll_languages") or "").find("Autre") >= 0 and not (e.get("enroll_custom_language") or "").strip():
        out.append("custom_language")
    if e.get("enroll_if_company"):
        for k, col in (("company_name", "enroll_company_name"), ("company_sector", "enroll_company_sector"), ("company_type", "enroll_company_type"), ("rc_file", "enroll_rc_file")):
            if not e.get(col):
                out.append(k)
    idt = e.get("enroll_id_type")
    if not idt or idt not in ID_TYPES:
        out.append("id_type")
    if not e.get("enroll_id_file"):
        out.append("id_file")
    if idt in ID_TYPES and ID_TYPES[idt] and not e.get("enroll_id_file_verso"):
        out.append("id_file_verso")
    sig = {"key": "signature", "label": "Signature du contrat"}
    res = [{"key": k, "label": FIELD_LABELS[k]} for k in out]
    if not e.get("enroll_signature"):
        res.append(sig)
    return res


def serialize_enrollment(e: dict | None) -> dict | None:
    if not e:
        return None
    return {
        "id": e["enroll_id"], "status": e["enroll_status"],
        "is_professional": e.get("enroll_is_professional") or 0, "is_expert": e.get("enroll_is_expert") or 0, "if_company": e.get("enroll_if_company") or 0,
        "company_name": e.get("enroll_company_name") or "", "company_sector": e.get("enroll_company_sector") or "", "company_type": e.get("enroll_company_type") or "",
        "study_level": e.get("enroll_study_level") or "", "languages": e.get("enroll_languages") or "", "custom_language": e.get("enroll_custom_language") or "",
        "id_type": e.get("enroll_id_type") or "", "id_number": e.get("enroll_id_number") or "",
        "id_file": e.get("enroll_id_file") or "", "id_file_verso": e.get("enroll_id_file_verso") or "", "rc_file": e.get("enroll_rc_file") or "",
        "casier_file": e.get("enroll_casier_file") or "", "cef_files": jlist(e.get("enroll_cef_files")), "diploma_files": jlist(e.get("enroll_diploma_files")),
        "cv_files": jlist(e.get("enroll_cv_files")), "has_signature": bool(e.get("enroll_signature")), "signature": e.get("enroll_signature") or None,
        "signature_pending": bool(e.get("enroll_signature_pending")), "contract_pdf": e.get("enroll_contract_pdf") or None,
        "admin_note": e.get("enroll_admin_note") or None, "updated_at": e["enroll_updated_at"].isoformat() if e.get("enroll_updated_at") else None,
        "created_at": e["enroll_created_at"].isoformat() if e.get("enroll_created_at") else None,
    }


# --------------------------------------------------------------------------- etat global
def state(db: Session, vendor_id: int) -> dict:
    v = vendor_row(db, vendor_id) or {}
    e = enrollment_row(db, vendor_id)
    cur = have_currencies(db)
    p_done = profile_complete(v)
    status = (e or {}).get("enroll_status")
    missing = enrollment_missing(e)
    submitted = status in ("pending", "approved")
    return {
        "profile": {"complete": p_done, "missing": profile_missing(v, cur)},
        "enrollment": {"status": status or "none", "submitted": submitted, "missing": missing, "admin_note": (e or {}).get("enroll_admin_note")},
        "dashboard_unlocked": bool(p_done and submitted and not missing),
        "next_step": "profile" if not p_done else ("enrollment" if not (submitted and not missing) else "dashboard"),
    }


def now() -> datetime:
    return datetime.utcnow()


def norm_dob(value: str | None) -> str | None:
    """AAAA-MM-JJ (champ date du navigateur) -> JJ-MM-AAAA, le format enregistre par l'ancien site."""
    if not value:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not m:
        raise ValueError("Date de naissance invalide.")
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    try:
        born = datetime(y, mo, d)
    except ValueError:
        raise ValueError("Date de naissance invalide.")
    if born > datetime.utcnow() or y < 1900:
        raise ValueError("Date de naissance invalide.")
    return f"{d:02d}-{mo:02d}-{y}"
