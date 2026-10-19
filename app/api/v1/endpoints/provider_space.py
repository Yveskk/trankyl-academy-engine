"""Espace prestataire (apres l'inscription) : profil, formulaire d'enrolement, tableau de bord.

Parcours : 1) completer le profil  2) remplir et soumettre le formulaire d'enrolement  3) tableau de bord.
Les champs et les regles sont ceux de l'ancien site Trankyl ; les donnees vivent dans les memes tables."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_apprenant
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.user import Apprenant
from app.services import enrollment_files as ef
from app.services import geocode as gc
from app.services import enrollment_mail as em
from app.services import provider_onboarding as ob
from app.services.image_upload import ImageUploadError, upload_image
from app.services.security import accounts as sec

router = APIRouter()


def get_provider(current: Apprenant = Depends(get_current_apprenant)) -> Apprenant:
    if current.academy_status not in ("provider", "certified_provider"):
        raise HTTPException(status_code=403, detail="Espace réservé aux prestataires.")
    return current


# --------------------------------------------------------------------------- etat et listes
@router.get("/onboarding")
def onboarding(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    return ob.state(db, provider.id)


@router.get("/options")
def options(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    def rows(sql: str):
        try:
            return db.execute(text(sql)).fetchall()
        except Exception:  # noqa: BLE001  (table absente d'une base ancienne)
            db.rollback()
            return []

    return {
        "countries": [{"id": r[0], "name": r[1]} for r in rows("SELECT country_id, country_name FROM countries WHERE country_is_active=1 ORDER BY country_name")],
        "currencies": [{"id": r[0], "label": f"{r[2]} ({r[1]})"} for r in rows("SELECT currency_id, currency_code, currency_wording FROM currencies ORDER BY currency_wording")],
        "districts": [{"id": r[0], "name": r[1]} for r in rows("SELECT district_id, district_name FROM district WHERE district_is_active=1 ORDER BY district_name")],
    }


# --------------------------------------------------------------------------- localisation
def _place(db: Session, lat: float, lng: float) -> dict:
    try:
        g = gc.reverse(lat, lng)
    except gc.GeocodeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    cid = db.execute(text("SELECT country_id FROM countries WHERE UPPER(country_code)=:c ORDER BY country_is_active DESC LIMIT 1"), {"c": g["country_code"]}).scalar() if g["country_code"] else None
    line = ", ".join(x for x in (" ".join(y for y in (g["street_number"], g["street_name"]) if y), g["area"]) if x)
    return {"latitude": round(lat, 7), "longitude": round(lng, 7), "country_id": cid, "country_code": g["country_code"], "city": g["city"], "street_number": g["street_number"],
            "street_name": g["street_name"], "postal_code": g["postal_code"], "address": line, "area": g["area"], "geolocation": f"https://www.google.com/maps?q={round(lat, 7)},{round(lng, 7)}"}


@router.get("/geocode/reverse")
@limiter.limit("30/minute")
def geocode_reverse(request: Request, lat: float, lng: float, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Position (GPS / carte) -> pays, ville, rue, code postal."""
    return _place(db, lat, lng)


@router.get("/geocode/link")
@limiter.limit("20/minute")
def geocode_link(request: Request, url: str, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Lien Google Maps (court ou long) -> position, puis pays, ville, rue, code postal."""
    try:
        lat, lng = gc.coords_from_url(url.strip())
    except gc.GeocodeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _place(db, lat, lng)


# --------------------------------------------------------------------------- profil
def _profile_out(v: dict) -> dict:
    sex = {"M": "Male", "F": "Female"}.get(v.get("vendor_sex") or "", "")
    dob = v.get("vendor_dob") or ""
    if dob and len(dob) == 10 and dob[2] == "-" and dob[5] == "-":  # JJ-MM-AAAA -> AAAA-MM-JJ (champ date du navigateur)
        dob = f"{dob[6:]}-{dob[3:5]}-{dob[:2]}"
    img = v.get("vendor_image") or ""
    return {
        "fname": v.get("vendor_name") or "", "family_name": v.get("vendor_family_name") or "", "email": v.get("vendor_email") or "", "phone": v.get("vendor_phone") or "",
        "country_code": v.get("vendor_country_code") or "", "sex": sex, "dob": dob, "address": v.get("vendor_address") or "",
        "vendor_address_country": str(v["vendor_address_country"]) if v.get("vendor_address_country") else "", "vendor_address_city": v.get("vendor_address_city") or "",
        "street_number": v.get("vendor_street_number") or "", "street_name": v.get("vendor_street_name") or "", "postal_code": v.get("vendor_postal_code") or "",
        "latitude": float(v["vendor_latitude"]) if v.get("vendor_latitude") is not None else None, "longitude": float(v["vendor_longitude"]) if v.get("vendor_longitude") is not None else None,
        "geolocation": (v.get("vendor_geolocation") or "").strip(), "bio": (v.get("vendor_bio") or "").strip(), "if_company": bool(v.get("vendor_if_company")),
        "company_name": v.get("company_name") or "", "vendor_currency": str(v["vendor_currency_id"]) if v.get("vendor_currency_id") else "",
        "working_district": v.get("vendor_working_district") or "", "image": img if img.startswith("https://") else None, "complete": ob.profile_complete(v),
    }


@router.get("/profile")
def get_profile(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    v = ob.vendor_row(db, provider.id)
    return {**_profile_out(v), "missing": ob.profile_missing(v, ob.have_currencies(db))}


@router.put("/profile")
@limiter.limit("20/minute")
async def save_profile(request: Request, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    form = await request.form()
    g = lambda k: (str(form.get(k) or "")).strip()  # noqa: E731
    errors: dict[str, str] = {}
    fname, family, email, sex = " ".join(g("fname").split()), " ".join(g("family_name").split()), g("email").lower(), g("sex")
    sex = {"Male": "M", "Female": "F", "M": "M", "F": "F"}.get(sex, "")
    if not fname:
        errors["fname"] = "Le prénom est obligatoire"
    if not family:
        errors["family_name"] = "Le nom de famille est obligatoire"
    import re

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", email):
        errors["email"] = "Un email valide est obligatoire"
    elif db.execute(text("SELECT 1 FROM vendors WHERE vendor_email=:e AND vendor_id<>:i LIMIT 1"), {"e": email, "i": provider.id}).first():
        errors["email"] = "Un compte existe déjà avec cet email"
    if not sex:
        errors["sex"] = "Le sexe est obligatoire"
    try:
        dob = ob.norm_dob(g("dob"))
        if not dob:
            errors["dob"] = "La date de naissance est obligatoire"
    except ValueError as e:
        dob, errors["dob"] = None, str(e)
    country = g("vendor_address_country")
    if not country.isdigit() or not db.execute(text("SELECT 1 FROM countries WHERE country_id=:c"), {"c": int(country)}).first():
        errors["vendor_address_country"] = "Le pays est obligatoire"
    city = g("vendor_address_city")
    if not city:
        errors["vendor_address_city"] = "La ville est obligatoire"
    lat = lng = None
    try:
        if g("latitude") and g("longitude"):
            lat, lng = float(g("latitude")), float(g("longitude"))
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
    except ValueError:
        lat = lng = None
        errors["address"] = "Position géographique invalide"
    address = g("address")[:500]
    if lat is None and not address:
        errors.setdefault("address", "L'adresse est obligatoire")
    currency = g("vendor_currency")
    if ob.have_currencies(db):
        if not currency.isdigit() or not db.execute(text("SELECT 1 FROM currencies WHERE currency_id=:c"), {"c": int(currency)}).first():
            errors["vendor_currency"] = "La devise est obligatoire"
    bio = g("bio")
    if len(bio) > 500:
        errors["bio"] = "La description ne peut pas dépasser 500 caractères"
    image_url = None
    image = form.get("image")
    if image is not None and hasattr(image, "read"):
        data = await image.read(ef.MAX_FILE_BYTES + 1)
        if data:
            kind = ef.sniff(data)
            if kind not in ("image/jpeg", "image/png", "image/webp") or len(data) > ef.MAX_FILE_BYTES:
                errors["image"] = "Photo de profil : JPG, PNG ou WebP, 5 Mo maximum"
            else:
                try:
                    image_url = upload_image(data, kind)
                except ImageUploadError as e:
                    raise HTTPException(status_code=502, detail=str(e))
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Veuillez corriger les champs signalés.", "errors": errors})

    sets = {
        "vendor_name": fname, "vendor_family_name": family, "vendor_email": email, "vendor_sex": sex, "vendor_dob": dob, "vendor_address_country": int(country),
        "vendor_address_city": city, "vendor_address": address or None, "vendor_street_number": g("street_number")[:255] or None, "vendor_street_name": g("street_name")[:255] or None,
        "vendor_postal_code": g("postal_code")[:10] or None, "vendor_latitude": lat, "vendor_longitude": lng, "vendor_geolocation": g("geolocation")[:255] or None,
        "vendor_bio": bio or None, "vendor_if_company": 1 if g("if_company") in ("1", "true", "on") else 0, "company_name": g("company_name")[:255] or None,
        "vendor_if_prof_comp": "1",
    }
    # Le pays choisi dans le profil est le pays du prestataire : c'est lui qui le range dans les listes admin (par pays),
    # y compris son dossier d'enrolement (sinon il resterait dans le pays de l'inscription, differente de ce choix).
    iso = db.execute(text("SELECT UPPER(country_code) FROM countries WHERE country_id=:c"), {"c": int(country)}).scalar()
    sets["vendor_country_id"] = int(country)
    if iso:
        sets["vendor_country_code"] = iso[:10]
    if "working_district" in form:  # champ retire du formulaire : une valeur deja enregistree (ancien site) n'est plus effacee
        sets["vendor_working_district"] = g("working_district")[:2000] or None
    if currency.isdigit():
        sets["vendor_currency_id"] = int(currency)
    if image_url:
        sets["vendor_image"] = image_url
    db.execute(text("UPDATE vendors SET " + ", ".join(f"{k}=:{k}" for k in sets) + " WHERE vendor_id=:_id"), {**sets, "_id": provider.id})
    db.commit()
    sec.log_event(db, "profile_updated", role="apprenant", account_id=provider.id, ip=sec.client_ip(request), ua=sec.client_agent(request), detail="prestataire")
    v = ob.vendor_row(db, provider.id)
    return {**_profile_out(v), "missing": ob.profile_missing(v, ob.have_currencies(db))}


# --------------------------------------------------------------------------- enrolement
SINGLE = {"id_file": "enroll_id_file", "id_file_verso": "enroll_id_file_verso", "rc_file": "enroll_rc_file", "casier_file": "enroll_casier_file"}
MULTI = {"diploma_files": "enroll_diploma_files", "cv_files": "enroll_cv_files", "cef_files": "enroll_cef_files"}
LABELS = {**ob.FIELD_LABELS}


@router.get("/enrollment")
def get_enrollment(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    e = ob.enrollment_row(db, provider.id)
    return {"enrollment": ob.serialize_enrollment(e), "missing": ob.enrollment_missing(e), "contract_text": ef.CONTRACT_TEXT}


@router.put("/enrollment")
@limiter.limit("30/minute")
async def save_enrollment(request: Request, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Enregistre le brouillon (une etape a la fois). Les fichiers sont verifies d'apres leur contenu."""
    if not ob.profile_complete(ob.vendor_row(db, provider.id) or {}):
        raise HTTPException(status_code=409, detail="Complétez d'abord votre profil.")
    cur = ob.enrollment_row(db, provider.id)
    if cur and cur["enroll_status"] in ("pending", "approved"):
        raise HTTPException(status_code=409, detail="Votre dossier est déjà soumis : il ne peut plus être modifié pendant l'examen.")
    form = await request.form()
    g = lambda k: (str(form.get(k) or "")).strip()  # noqa: E731
    cols: dict = {}

    def num(k: str, allowed=(0, 1)):
        if k in form:
            try:
                v = int(g(k) or 0)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Valeur invalide : {k}.")
            if v not in allowed:
                raise HTTPException(status_code=422, detail=f"Valeur invalide : {k}.")
            return v
        return None

    for key, col, allowed in (("is_professional", "enroll_is_professional", (0, 1, 2)), ("is_expert", "enroll_is_expert", (0, 1)), ("if_company", "enroll_if_company", (0, 1))):
        v = num(key, allowed)
        if v is not None:
            cols[col] = v
    for key, col, ok in (("company_sector", "enroll_company_sector", ob.SECTORS), ("company_type", "enroll_company_type", ob.LEGAL_FORMS), ("study_level", "enroll_study_level", ob.STUDY_LEVELS)):
        if key in form:
            if g(key) and g(key) not in ok:
                raise HTTPException(status_code=422, detail=f"Valeur invalide : {LABELS[key]}.")
            cols[col] = g(key) or None
    if "company_name" in form:
        cols["enroll_company_name"] = g("company_name")[:255] or None
    if "languages" in form:
        langs = [x for x in (s.strip() for s in g("languages").split(",")) if x]
        if any(x not in ob.LANGUAGES for x in langs):
            raise HTTPException(status_code=422, detail="Langue invalide.")
        cols["enroll_languages"] = ", ".join(langs) or None
    if "custom_language" in form:
        cols["enroll_custom_language"] = g("custom_language")[:255] or None
    if "id_type" in form:
        if g("id_type") and g("id_type") not in ob.ID_TYPES:
            raise HTTPException(status_code=422, detail="Type de pièce invalide.")
        cols["enroll_id_type"] = g("id_type") or None
    if "id_number" in form:
        cols["enroll_id_number"] = g("id_number")[:255] or None

    clear = set()
    try:
        clear = set(json.loads(g("clear") or "[]"))
    except ValueError:
        pass
    existing = ob.serialize_enrollment(cur) or {}
    try:
        for key, col in SINGLE.items():
            f = form.get(key)
            if f is not None and hasattr(f, "read"):
                data = await f.read(ef.MAX_FILE_BYTES + 1)
                if data:
                    cols[col] = ef.upload_document(data, LABELS[key])
                    continue
            if key in clear:
                cols[col] = None
        for key, col in MULTI.items():
            keep = []
            try:
                keep = [u for u in json.loads(g(f"keep_{key}") or "null") or []] if f"keep_{key}" in form else existing.get(key, [])
            except ValueError:
                keep = existing.get(key, [])
            keep = [u for u in keep if u in existing.get(key, [])]  # on ne garde que des fichiers deja enregistres
            news = [f for f in form.getlist(key) if hasattr(f, "read")]
            if f"keep_{key}" in form or news:
                urls = list(keep)
                for f in news:
                    data = await f.read(ef.MAX_FILE_BYTES + 1)
                    if data:
                        if len(urls) >= ef.MAX_MULTI:
                            raise HTTPException(status_code=422, detail=f"{LABELS[key]} : {ef.MAX_MULTI} fichiers maximum.")
                        urls.append(ef.upload_document(data, LABELS[key]))
                cols[col] = json.dumps(urls) if urls else None
    except ef.FileRejected as e:
        raise HTTPException(status_code=422, detail=str(e))
    if "signature" in form:
        sig = g("signature")
        if sig and ef.signature_png(sig) is None:
            raise HTTPException(status_code=422, detail="Signature invalide : signez à nouveau.")
        cols["enroll_signature"] = sig or None
        if sig:
            cols["enroll_contract_pdf"] = None  # regenere a la soumission
    cols["enroll_updated_at"] = ob.now()
    if cur:
        db.execute(text("UPDATE vendor_enrollments SET " + ", ".join(f"{k}=:{k}" for k in cols) + " WHERE enroll_id=:_id"), {**cols, "_id": cur["enroll_id"]})
    else:
        v = ob.vendor_row(db, provider.id)
        base = {"enroll_vendor_id": provider.id, "enroll_status": "draft", "enroll_name": v.get("vendor_name"), "enroll_family_name": v.get("vendor_family_name"),
                "enroll_phone": v.get("vendor_phone"), "enroll_email": v.get("vendor_email"), "enroll_created_at": ob.now(), **cols}
        db.execute(text("INSERT INTO vendor_enrollments (" + ", ".join(base) + ") VALUES (" + ", ".join(f":{k}" for k in base) + ")"), base)
    db.commit()
    e = ob.enrollment_row(db, provider.id)
    return {"enrollment": ob.serialize_enrollment(e), "missing": ob.enrollment_missing(e)}


@router.post("/enrollment/submit")
@limiter.limit("10/minute")
def submit_enrollment(request: Request, tasks: BackgroundTasks, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    v = ob.vendor_row(db, provider.id) or {}
    if not ob.profile_complete(v):
        raise HTTPException(status_code=409, detail="Complétez d'abord votre profil.")
    e = ob.enrollment_row(db, provider.id)
    if not e:
        raise HTTPException(status_code=422, detail={"message": "Le formulaire est vide.", "missing": ob.enrollment_missing(None)})
    if e["enroll_status"] in ("pending", "approved"):
        raise HTTPException(status_code=409, detail="Votre dossier est déjà soumis.")
    missing = ob.enrollment_missing(e)
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Informations importantes manquantes : " + ", ".join(m["label"] for m in missing), "missing": missing})
    contract_url = None
    try:
        png = ef.contract_image(e["enroll_signature"], f"{v.get('vendor_name') or ''} {v.get('vendor_family_name') or ''}".strip())
        contract_url = ef.upload_document(png, "Contrat signé")
    except Exception:  # noqa: BLE001  (le contrat est un plus : son echec ne bloque pas la soumission, l'admin voit la signature)
        import logging

        logging.getLogger("enrollment").warning("Contrat signé non généré pour le prestataire %s", provider.id, exc_info=True)
    resubmitted = e["enroll_status"] == "rejected"
    db.execute(
        text("UPDATE vendor_enrollments SET enroll_status='pending', enroll_contract_pdf=COALESCE(:c, enroll_contract_pdf), enroll_updated_at=:n WHERE enroll_id=:i"),
        {"c": contract_url, "n": ob.now(), "i": e["enroll_id"]},
    )
    db.execute(text("UPDATE vendors SET vendor_if_prof_comp='1' WHERE vendor_id=:i"), {"i": provider.id})  # compte active : profil complet
    db.commit()
    sec.log_event(db, "enrollment_submitted", role="apprenant", account_id=provider.id, ip=sec.client_ip(request), ua=sec.client_agent(request))
    country = db.execute(text("SELECT country_name FROM countries WHERE country_id=:c"), {"c": v.get("vendor_address_country")}).scalar() if v.get("vendor_address_country") else None
    tasks.add_task(
        em.notify_submission,
        {"vendor_name": f"{v.get('vendor_name') or ''} {v.get('vendor_family_name') or ''}".strip() or "Un prestataire", "vendor_phone": v.get("vendor_phone"), "vendor_email": v.get("vendor_email"),
         "resubmitted": resubmitted, "study_level": e.get("enroll_study_level"), "languages": e.get("enroll_languages"), "company_name": e.get("enroll_company_name"),
         "country": country, "enrollment_id": e["enroll_id"]},
    )
    return {**ob.state(db, provider.id), "enrollment_status": "pending"}


# --------------------------------------------------------------------------- tableau de bord
@router.get("/dashboard")
def dashboard(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    st = ob.state(db, provider.id)
    if not st["dashboard_unlocked"]:
        raise HTTPException(status_code=409, detail={"message": "Terminez d'abord votre profil et votre formulaire d'enrôlement.", "next_step": st["next_step"]})
    v = ob.vendor_row(db, provider.id) or {}
    e = ob.enrollment_row(db, provider.id) or {}
    approved = e.get("enroll_status") == "approved"
    rows = db.execute(
        text(
            "SELECT b.bk_id, b.bk_unique_id, b.bk_date, b.bk_service_status, b.bk_total_amount, b.bk_amount_remaining, b.bk_client_id, b.bk_client_name, b.bk_created_at, s.s_title "
            "FROM bookings b LEFT JOIN services s ON s.s_id=b.bk_service_id WHERE b.bk_vendor_id=:v ORDER BY b.bk_created_at DESC, b.bk_id DESC LIMIT 500"
        ),
        {"v": provider.id},
    ).fetchall()
    month = datetime.utcnow().strftime("%Y-%m")
    num = lambda x: float(x or 0) if str(x or "0").replace(".", "", 1).isdigit() else 0.0  # noqa: E731
    status_of = {None: "pending", "0": "pending", "1": "pending", "2": "completed", "3": "cancelled", "4": "cancelled"}
    revenue = sum(num(r[5]) or num(r[4]) for r in rows if status_of.get(r[3], "pending") == "completed" and r[8] and r[8].strftime("%Y-%m") == month)
    per_client: dict = {}
    for r in rows:
        if r[6]:
            per_client[r[6]] = per_client.get(r[6], 0) + 1
    pending_n = sum(1 for r in rows if status_of.get(r[3], "pending") == "pending")
    pending_bk = "À vérifier" if not approved else "Validé"
    steps = [
        {"key": "phone", "label": "Téléphone", "status": "validated", "detail": None},
        {"key": "identity", "label": "Pièce d'identité", "status": "validated" if approved else "review", "detail": None},
        {"key": "selfie", "label": "Selfie de contrôle", "status": "todo", "detail": None},
        {"key": "address", "label": "Adresse", "status": "validated" if (v.get("vendor_address") or v.get("vendor_latitude") is not None) and ob.profile_complete(v) else "todo", "detail": None},
        {"key": "training", "label": "Formation obligatoire", "status": "validated" if v.get("vendor_training_completed") else "todo", "detail": None},
        {"key": "references", "label": "Références", "status": "todo", "detail": None},
        {"key": "interview", "label": "Entretien Trankyl", "status": "validated" if v.get("vendor_interview_done") else "todo", "detail": None},
    ]
    done = sum(1 for s in steps if s["status"] == "validated")
    # Abonnement PRO : actif tant qu'une periode payee n'est pas echue. Illisible (table absente) -> pas d'alerte.
    try:
        end = db.execute(text("SELECT MAX(subs_end_date) FROM subscriptions WHERE subs_vendor_id=:v AND subs_is_active=1 AND subs_end_date>=:n"), {"v": provider.id, "n": datetime.utcnow()}).scalar()
        last = db.execute(text("SELECT MAX(subs_end_date) FROM subscriptions WHERE subs_vendor_id=:v AND subs_is_active=1"), {"v": provider.id}).scalar()
        subscription = {"active": bool(end), "ends_at": (end or last).isoformat() if (end or last) else None, "days_left": max(0, (end - datetime.utcnow()).days) if end else 0, "ever": bool(last)}
    except Exception:  # noqa: BLE001
        db.rollback()
        subscription = None
    return {
        "subscription": subscription,
        "id": provider.id, "name": v.get("vendor_name") or "", "city": v.get("vendor_address_city") or "", "photo": v.get("vendor_image") if str(v.get("vendor_image") or "").startswith("https://") else None,
        "enrollment_status": e.get("enroll_status"), "enrollment_note": e.get("enroll_admin_note"), "new_requests": pending_n,
        "verification": {"steps": steps, "done": done, "total": len(steps), "percent": round(100 * done / len(steps)), "label": pending_bk},
        "stats": {"revenue_month": revenue, "profile_views": None, "acceptance_rate": None, "loyal_clients": sum(1 for n in per_client.values() if n >= 2)},
        "recent": [{"id": r[0], "ref": r[1], "client": r[7], "service": r[9], "amount": num(r[5]) or num(r[4]), "status": status_of.get(r[3], "pending"), "date": r[2].isoformat() if r[2] else None} for r in rows[:6]],
    }
