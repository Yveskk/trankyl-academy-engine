"""Menu admin « Formulaires d'enrôlement » : examen des dossiers soumis par les prestataires.

Logique reprise de l'admin Trankyl (Angular) : liste filtrable par statut, detail avec une case a cocher par champ ;
approuver avec les champs non coches (le prestataire est prevenu de ce qu'il doit completer) ou refuser avec un motif
et les champs refuses ; validation ou refus d'un changement de signature. Meme table (`vendor_enrollments`) : les deux
administrations voient les memes dossiers.

Les brouillons (`draft`) n'apparaissent pas : seul un dossier SOUMIS est examinable."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_access
from app.db.session import get_db
from app.services import enrollment_mail as em
from app.services import provider_onboarding as ob
from app.services.countries import vendor_country_clause
from app.services.security import accounts as sec

router = APIRouter()
STATUSES = ("pending", "approved", "rejected")
GROUPS = [
    ("Profil professionnel", ["is_professional", "is_expert", "if_company", "company_name", "company_sector", "company_type", "study_level", "languages", "custom_language"]),
    ("Documents et pièces d'identité", ["id_type", "id_file", "id_file_verso", "rc_file", "casier_file", "cef_files", "diploma_files", "cv_files"]),
]
COLS = {
    "is_professional": "enroll_is_professional", "is_expert": "enroll_is_expert", "if_company": "enroll_if_company", "company_name": "enroll_company_name",
    "company_sector": "enroll_company_sector", "company_type": "enroll_company_type", "study_level": "enroll_study_level", "languages": "enroll_languages",
    "custom_language": "enroll_custom_language", "id_type": "enroll_id_type", "id_file": "enroll_id_file", "id_file_verso": "enroll_id_file_verso",
    "rc_file": "enroll_rc_file", "casier_file": "enroll_casier_file", "cef_files": "enroll_cef_files", "diploma_files": "enroll_diploma_files", "cv_files": "enroll_cv_files",
}
OPTIONAL = {"is_expert", "casier_file", "cef_files", "diploma_files", "cv_files"}  # facultatifs : vides, ils ne comptent pas comme « manquants »
KINDS = {"id_file": "file", "id_file_verso": "file", "rc_file": "file", "casier_file": "file", "cef_files": "files", "diploma_files": "files", "cv_files": "files"}
CHOICES = {
    "is_professional": {0: "Particulier", 1: "Professionnel", 2: "Expert"}, "is_expert": {0: "Non", 1: "Oui"}, "if_company": {0: "Non", 1: "Oui"},
    "company_sector": {"btp": "BTP / Construction", "transport": "Transport / Livraison", "maison": "Maison / Ménage", "jardinage": "Jardinage / Paysagisme", "informatique": "Informatique / Tech",
                       "beaute": "Beauté / Bien-être", "sante": "Santé / Médical", "education": "Éducation / Formation", "restauration": "Restauration / Alimentation", "autre": "Autre"},
    "company_type": {"auto_entrepreneur": "Auto-entrepreneur", "micro_entreprise": "Micro-entreprise", "sarl": "SARL", "sa": "SA", "sas": "SAS / SASU", "ei": "Entreprise individuelle", "autre": "Autre"},
    "study_level": {"aucun": "Aucune scolarité", "primaire": "Primaire", "college": "Collège / BEPC", "lycee": "Lycée / BAC", "bts": "BTS / DUT", "licence": "Licence (Bac+3)", "master": "Master (Bac+5)",
                    "doctorat": "Doctorat", "formation": "Formation professionnelle", "autre": "Autre"},
    "id_type": {"CNI": "Carte nationale d'identité", "CARTE_ELECTEUR": "Carte d'électeur", "PERMIS": "Permis de conduire", "PASSEPORT": "Passeport"},
}


def _scope(db: Session, admin) -> tuple[str, dict]:
    clause, params = vendor_country_clause(db, admin.country, "v")
    return f"e.enroll_status IN ('pending','approved','rejected') AND {clause}", params


FROM = "FROM vendor_enrollments e JOIN vendors v ON v.vendor_id=e.enroll_vendor_id"


@router.get("/admin")
def admin_list(
    status: str | None = None, q: str = "", page: int = 1, page_size: int = 20,
    admin=Depends(require_access("enrollment_forms", write="manage")), db: Session = Depends(get_db),
):
    scope, params = _scope(db, admin)
    where, p = [scope], dict(params)
    if q.strip():
        where.append("(v.vendor_name LIKE :q OR v.vendor_family_name LIKE :q OR v.vendor_phone LIKE :q OR v.vendor_email LIKE :q)")
        p["q"] = f"%{q.strip()}%"
    base = " AND ".join(where)
    counts = {s: db.execute(text(f"SELECT COUNT(*) {FROM} WHERE {base} AND e.enroll_status=:s"), {**p, "s": s}).scalar() or 0 for s in STATUSES}
    counts["all"] = sum(counts.values())
    shown = base + (" AND e.enroll_status=:status" if status in STATUSES else "")
    page, page_size = max(1, page), min(max(1, page_size), 100)
    rows = db.execute(
        text(
            "SELECT e.enroll_id, e.enroll_vendor_id, e.enroll_status, e.enroll_study_level, e.enroll_if_company, e.enroll_company_name, e.enroll_updated_at, e.enroll_created_at, "
            "v.vendor_name, v.vendor_family_name, v.vendor_phone, v.vendor_email, v.vendor_image, v.vendor_address_city, (e.enroll_signature_pending IS NOT NULL AND e.enroll_signature_pending<>'') "
            f"{FROM} WHERE {shown} ORDER BY e.enroll_updated_at DESC, e.enroll_id DESC LIMIT :lim OFFSET :off"
        ),
        {**p, **({"status": status} if status in STATUSES else {}), "lim": page_size, "off": (page - 1) * page_size},
    ).fetchall()
    items = [
        {
            "id": r[0], "vendor_id": r[1], "status": r[2], "study_level": CHOICES["study_level"].get(r[3] or "", r[3]), "company": r[5] if r[4] else None,
            "updated_at": r[6].isoformat() if r[6] else None, "created_at": r[7].isoformat() if r[7] else None,
            "name": " ".join(x for x in (r[8], r[9]) if x), "phone": r[10], "email": r[11] or None, "image": r[12] if str(r[12] or "").startswith("https://") else None,
            "city": r[13], "signature_pending": bool(r[14]),
        }
        for r in rows
    ]
    total = counts[status] if status in STATUSES else counts["all"]
    return {"total": total, "page": page, "page_size": page_size, "counts": counts, "items": items}


def _load(db: Session, admin, enroll_id: int) -> dict:
    scope, params = _scope(db, admin)
    r = db.execute(
        text(f"SELECT e.*, v.vendor_name, v.vendor_family_name, v.vendor_phone, v.vendor_email, v.vendor_image, v.vendor_address_city, v.vendor_address, v.vendor_country_code {FROM} WHERE e.enroll_id=:i AND {scope}"),
        {"i": enroll_id, **params},
    ).mappings().first()
    if r is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    return dict(r)


@router.get("/admin/{enroll_id}")
def admin_detail(enroll_id: int, admin=Depends(require_access("enrollment_forms", write="manage")), db: Session = Depends(get_db)):
    r = _load(db, admin, enroll_id)
    groups = []
    company = bool(r.get("enroll_if_company"))
    other_lang = "Autre" in (r.get("enroll_languages") or "")
    not_applicable = set() | (set() if company else {"company_name", "company_sector", "company_type", "rc_file", "cef_files"}) | ({"diploma_files", "cv_files"} if company else set()) | (set() if other_lang else {"custom_language"})
    for title, keys in GROUPS:
        fields = []
        for k in keys:
            if k in not_applicable:  # champ sans objet pour ce profil (ex. registre de commerce d'un particulier)
                continue
            raw = r.get(COLS[k])
            kind = KINDS.get(k, "text")
            if kind == "files":
                value, filled = ob.jlist(raw), bool(ob.jlist(raw))
            elif kind == "file":
                value, filled = raw or None, bool(raw)
            elif k in ("is_professional", "is_expert", "if_company"):
                value, filled = CHOICES[k].get(int(raw or 0)), raw is not None
            elif k in CHOICES:
                value, filled = (CHOICES[k].get(raw, raw) if raw not in (None, "") else None), raw not in (None, "")
            else:
                value, filled = (raw if raw not in (None, "") else None), raw not in (None, "")
            fields.append({"key": k, "label": ob.FIELD_LABELS[k], "kind": kind, "value": value, "filled": bool(filled), "optional": k in OPTIONAL})
        groups.append({"title": title, "fields": fields})
    return {
        "id": r["enroll_id"], "vendor_id": r["enroll_vendor_id"], "status": r["enroll_status"], "admin_note": r.get("enroll_admin_note"),
        "vendor": {"name": " ".join(x for x in (r["vendor_name"], r["vendor_family_name"]) if x), "phone": r["vendor_phone"], "email": r["vendor_email"] or None, "city": r["vendor_address_city"],
                   "address": r["vendor_address"], "image": r["vendor_image"] if str(r["vendor_image"] or "").startswith("https://") else None},
        "groups": groups, "signature": r.get("enroll_signature"), "signature_pending": r.get("enroll_signature_pending"), "signature_reason": r.get("enroll_signature_reason"),
        "contract_pdf": r.get("enroll_contract_pdf"), "id_number": r.get("enroll_id_number"),
        "created_at": r["enroll_created_at"].isoformat() if r.get("enroll_created_at") else None, "updated_at": r["enroll_updated_at"].isoformat() if r.get("enroll_updated_at") else None,
    }


class Decision(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=1000)
    # Libelles des champs NON valides (cases decochees) : a completer (approbation) ou refuses (refus).
    fields: list[str] = Field(default_factory=list, max_length=40)


@router.post("/admin/{enroll_id}/decision")
def decide(
    request: Request, enroll_id: int, payload: Decision, tasks: BackgroundTasks,
    admin=Depends(require_access("enrollment_forms", write="manage")), db: Session = Depends(get_db),
):
    r = _load(db, admin, enroll_id)
    if payload.status == "rejected" and not (payload.note or "").strip():
        raise HTTPException(status_code=422, detail="Indiquez le motif du refus : le prestataire le recevra.")
    known = set(ob.FIELD_LABELS.values()) | {"Signature du contrat"}
    fields = [f for f in payload.fields if f in known]
    db.execute(
        text("UPDATE vendor_enrollments SET enroll_status=:s, enroll_admin_note=:n, enroll_updated_at=:t WHERE enroll_id=:i"),
        {"s": payload.status, "n": (payload.note or "").strip() or None, "t": datetime.utcnow(), "i": enroll_id},
    )
    if payload.status == "approved":  # dossier valide : le prestataire est verifie (visible dans l'annuaire)
        db.execute(text("UPDATE vendors SET vendor_academy_verified=1, vendor_academy_verified_at=:t WHERE vendor_id=:v AND COALESCE(vendor_academy_verified,0)=0"), {"t": datetime.utcnow(), "v": r["enroll_vendor_id"]})
    db.commit()
    sec.log_event(db, "enrollment_" + payload.status, role="admin", account_id=getattr(admin, "id", None), ip=sec.client_ip(request), ua=sec.client_agent(request), detail=f"dossier {enroll_id}")
    from app.api.v1.endpoints.directory import clear_directory_cache

    clear_directory_cache()
    tasks.add_task(
        em.notify_decision,
        {"vendor_name": r["vendor_name"] or "", "decision": payload.status, "note": (payload.note or "").strip() or None, "missing": fields},
        r["vendor_email"],
    )
    return {"id": enroll_id, "status": payload.status}


class SignatureDecision(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


@router.post("/admin/{enroll_id}/signature")
def decide_signature(enroll_id: int, payload: SignatureDecision, admin=Depends(require_access("enrollment_forms", write="manage")), db: Session = Depends(get_db)):
    r = _load(db, admin, enroll_id)
    if not r.get("enroll_signature_pending"):
        raise HTTPException(status_code=409, detail="Aucun changement de signature en attente.")
    if payload.approve:
        db.execute(
            text("UPDATE vendor_enrollments SET enroll_signature=enroll_signature_pending, enroll_signature_pending=NULL, enroll_signature_reason=NULL, enroll_signature_pending_at=NULL, enroll_updated_at=:t WHERE enroll_id=:i"),
            {"t": datetime.utcnow(), "i": enroll_id},
        )
    else:
        db.execute(
            text("UPDATE vendor_enrollments SET enroll_signature_pending=NULL, enroll_signature_reason=NULL, enroll_signature_pending_at=NULL, enroll_updated_at=:t WHERE enroll_id=:i"),
            {"t": datetime.utcnow(), "i": enroll_id},
        )
    db.commit()
    return {"id": enroll_id, "signature": "approved" if payload.approve else "rejected"}
