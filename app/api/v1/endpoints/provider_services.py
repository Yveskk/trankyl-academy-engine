"""Espace prestataire — creation et gestion de SES services (table partagee `services`, la meme que celle de l'app
prestataire Trankyl et du backend Node).

Formats ecrits : identiques a ceux de l'app (`s_sub_services` JSON [{unit_id, price}], `s_options` PHP serialise,
`s_exp` "3 years", `s_district_id` identifiants separes par des virgules, images en URLs separees par des virgules).
Le pays du service est celui du prestataire ; un service est visible des sa creation."""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.api.v1.endpoints.directory import clear_directory_cache
from app.api.v1.endpoints.provider_space import get_provider
from app.api.v1.endpoints.provider_work import _image
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.user import Apprenant
from app.services import php_serialize
from app.services.home import invalidate_home_cache

router = APIRouter()

MAX_SERVICES = 50
MAX_IMAGES = 6
MAX_UNITS = 12
MAX_OPTIONS = 10
MAX_PRICE = 10_000_000
HTTPS = re.compile(r"^https://\S+$")


def _pick(lang: str, fr, en):
    return en if lang == "en" and en else fr


def _ids(raw: str | None) -> list[int]:
    return [int(x) for x in re.split(r"[,\s]+", raw or "") if x.isdigit()]


def _json(raw: str | None):
    try:
        return json.loads(raw or "")
    except ValueError:
        return None


# --------------------------------------------------------------------------- referentiels
@router.get("/services/catalog")
def catalog(lang: str = "fr", provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Metiers (categories > sous-categories) et unites de tarification de chaque sous-categorie : UNE reponse."""
    unit_rows = db.execute(text("SELECT sv_unit_id, sv_unit_wording_fr, sv_unit_wording_en FROM service_unities")).fetchall()
    units = {r[0]: {"id": r[0], "label": _pick(lang, r[1], r[2])} for r in unit_rows}
    cats = db.execute(text("SELECT cat_id, cat_name_fr, cat_name_en FROM categories ORDER BY cat_order, cat_id")).fetchall()
    subs = db.execute(
        text("SELECT subcat_id, subcat_cat_id, subcat_name_fr, subcat_name_en, subcat_desp_fr, subcat_desp_en, subcat_image, subcat_extention FROM sub_categories WHERE subcat_is_active=1 ORDER BY subcat_name_fr")
    ).fetchall()
    by_cat: dict[str, list] = {}
    for r in subs:
        ids = _json(r[7])
        by_cat.setdefault(str(r[1]), []).append(
            {
                "id": r[0], "name": _pick(lang, r[2], r[3]), "description": _pick(lang, r[4], r[5]) if len(str(_pick(lang, r[4], r[5]) or "")) > 2 else None, "image_url": r[6],
                "units": [units[int(i)] for i in (ids if isinstance(ids, list) else []) if str(i).isdigit() and int(i) in units],
            }
        )
    return {"categories": [{"id": c[0], "name": _pick(lang, c[1], c[2]), "subcategories": by_cat.get(str(c[0]), [])} for c in cats if by_cat.get(str(c[0]))]}


def _provider_country(provider: Apprenant) -> int:
    if not provider.country_id:
        raise HTTPException(status_code=422, detail="Renseignez votre pays dans « Mon profil » avant de créer un service.")
    return int(provider.country_id)


@router.get("/services/locations")
def locations(provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Villes du pays du prestataire et leurs quartiers (une requete)."""
    cid = _provider_country(provider)
    rows = db.execute(
        text(
            "SELECT c.city_id, c.city_name, d.district_id, d.district_name FROM cities c LEFT JOIN district d ON d.district_city_id=c.city_id AND d.district_is_active=1 "
            "WHERE c.city_is_active=1 AND c.city_country_id=:c ORDER BY c.city_name, d.district_name"
        ),
        {"c": cid},
    ).fetchall()
    out: dict[int, dict] = {}
    for city_id, city_name, did, dname in rows:
        e = out.setdefault(city_id, {"id": city_id, "name": city_name, "districts": []})
        if did:
            e["districts"].append({"id": did, "name": dname})
    country = db.execute(text("SELECT country_name FROM countries WHERE country_id=:c"), {"c": cid}).scalar()
    mine = (provider.address_city or "").strip().lower()
    default_city = next((c["id"] for c in out.values() if c["name"].strip().lower() == mine), None)
    return {"country": {"id": cid, "name": country}, "cities": list(out.values()), "default_city_id": default_city}


# --------------------------------------------------------------------------- lecture
_SELECT = (
    "SELECT s.s_id, s.s_subcat_id, s.s_title, s.s_desp, s.s_exp, s.s_sub_services, s.s_options, s.s_min_price, s.s_tools_used, s.s_notes, s.s_image, s.s_type, "
    "s.s_city_id, s.s_district_id, s.s_country_id, s.s_is_active, s.s_created_at, sc.subcat_name_fr, sc.subcat_name_en, ca.cat_name_fr, ca.cat_name_en, "
    "(SELECT COUNT(*) FROM bookings b WHERE b.bk_service_id=s.s_id) AS n_bookings, "
    "(SELECT COUNT(*) FROM bookings b WHERE b.bk_service_id=s.s_id AND b.bk_service_status='2') AS n_done, "
    "(SELECT COALESCE(SUM(b.bk_total_amount),0) FROM bookings b WHERE b.bk_service_id=s.s_id AND b.bk_service_status='2') AS revenue "
    "FROM services s LEFT JOIN sub_categories sc ON sc.subcat_id=s.s_subcat_id LEFT JOIN categories ca ON ca.cat_id=sc.subcat_cat_id "
    "WHERE s.s_vendor_id=:v AND (s.s_is_deleted IS NULL OR s.s_is_deleted NOT IN ('1','true'))"
)


def _lookups(db: Session, rows, lang: str):
    unit_ids = set()
    district_ids: set[int] = set()
    city_ids: set[int] = set()
    for r in rows:
        for u in _json(r[5]) or []:
            if isinstance(u, dict) and str(u.get("unit_id", "")).isdigit():
                unit_ids.add(int(u["unit_id"]))
        district_ids.update(_ids(r[13]))
        if str(r[12] or "").isdigit():
            city_ids.add(int(r[12]))

    def fetch(sql: str, ids: set[int]) -> list:
        if not ids:
            return []
        return db.execute(text(sql).bindparams(bindparam("i", expanding=True)), {"i": list(ids)}).fetchall()

    units = {r[0]: _pick(lang, r[1], r[2]) for r in fetch("SELECT sv_unit_id, sv_unit_wording_fr, sv_unit_wording_en FROM service_unities WHERE sv_unit_id IN :i", unit_ids)}
    districts = {r[0]: r[1] for r in fetch("SELECT district_id, district_name FROM district WHERE district_id IN :i", district_ids)}
    cities = {r[0]: r[1] for r in fetch("SELECT city_id, city_name FROM cities WHERE city_id IN :i", city_ids)}
    return units, districts, cities


def _out(r, lookups, lang: str, detail: bool = True) -> dict:
    units, districts, cities = lookups
    tarifs = []
    for u in _json(r[5]) or []:
        if isinstance(u, dict) and str(u.get("unit_id", "")).isdigit():
            tarifs.append({"unit_id": int(u["unit_id"]), "label": units.get(int(u["unit_id"])), "price": int(float(u.get("price") or 0))})
    options = [{"name": str(o.get("name", "")), "price": int(float(o.get("price") or 0))} for o in php_serialize.load_list(r[6]) if isinstance(o, dict) and o.get("name")]
    years = re.match(r"\s*(\d+)", str(r[4] or ""))
    images = [u for u in str(r[10] or "").split(",") if u.startswith("http")]
    did = _ids(r[13])
    out = {
        "id": r[0], "title": r[2], "subcategory": {"id": int(r[1]) if str(r[1]).isdigit() else None, "name": _pick(lang, r[17], r[18])}, "category": _pick(lang, r[19], r[20]),
        "min_price": int(r[7] or 0), "units": tarifs, "options": options, "images": images, "image": images[0] if images else None,
        "is_active": str(r[15]) == "1", "type": "online" if str(r[11]) == "0" else "home", "city": cities.get(int(r[12])) if str(r[12] or "").isdigit() else None,
        "districts": [districts[i] for i in did if i in districts], "created_at": r[16].isoformat() if r[16] else None,
        "stats": {"bookings": int(r[21] or 0), "completed": int(r[22] or 0), "revenue": int(float(r[23] or 0))},
    }
    if detail:
        out.update(
            {
                "description": r[3], "experience_years": int(years.group(1)) if years else 0, "tools": [t.strip() for t in str(r[8] or "").split(",") if t.strip()], "notes": r[9] or "",
                "city_id": int(r[12]) if str(r[12] or "").isdigit() else None, "district_ids": did,
            }
        )
    return out


@router.get("/services")
def list_services(lang: str = "fr", provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    rows = db.execute(text(_SELECT + " ORDER BY s.s_id DESC LIMIT 200"), {"v": str(provider.id)}).fetchall()
    lk = _lookups(db, rows, lang)
    items = [_out(r, lk, lang, detail=False) for r in rows]
    return {"total": len(items), "active": sum(1 for i in items if i["is_active"]), "limit": MAX_SERVICES, "items": items}


def _load(db: Session, provider: Apprenant, service_id: int):
    row = db.execute(text(_SELECT + " AND s.s_id=:i"), {"v": str(provider.id), "i": service_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Service introuvable.")
    return row


@router.get("/services/{service_id}")
def get_service(service_id: int, lang: str = "fr", provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    r = _load(db, provider, service_id)
    return _out(r, _lookups(db, [r], lang), lang)


# --------------------------------------------------------------------------- ecriture
class UnitIn(BaseModel):
    unit_id: int = Field(ge=0)  # 0 = forfait (sous-categorie sans unite de tarification)
    price: int = Field(ge=1, le=MAX_PRICE)


class OptionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price: int = Field(ge=0, le=MAX_PRICE)


class ServiceIn(BaseModel):
    subcategory_id: int
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    experience_years: int = Field(ge=0, le=60)
    units: list[UnitIn] = Field(min_length=1, max_length=MAX_UNITS)
    options: list[OptionIn] = Field(default_factory=list, max_length=MAX_OPTIONS)
    tools: list[str] = Field(default_factory=list, max_length=15)
    notes: str = Field(default="", max_length=1000)
    images: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)
    type: str = "home"  # "home" (se deplace / lieu physique) ou "online"
    city_id: int | None = None
    district_ids: list[int] = Field(default_factory=list, max_length=200)
    is_active: bool = True


def _values(db: Session, provider: Apprenant, p: ServiceIn) -> dict:
    cid = _provider_country(provider)
    sub = db.execute(text("SELECT subcat_extention FROM sub_categories WHERE subcat_id=:i AND subcat_is_active=1"), {"i": p.subcategory_id}).first()
    if not sub:
        raise HTTPException(status_code=422, detail="Métier introuvable.")
    allowed = {int(i) for i in (_json(sub[0]) or []) if str(i).isdigit()}
    seen: set[int] = set()
    for u in p.units:
        if (u.unit_id not in allowed) if allowed else (u.unit_id != 0):  # sans unite definie : un forfait (unit_id 0)
            raise HTTPException(status_code=422, detail="Une unité de tarification ne correspond pas à ce métier.")
        if u.unit_id in seen:
            raise HTTPException(status_code=422, detail="Chaque unité de tarification ne peut être utilisée qu'une fois.")
        seen.add(u.unit_id)
    if not all(HTTPS.match(i) for i in p.images):
        raise HTTPException(status_code=422, detail="Image invalide.")
    if p.type not in ("home", "online"):
        raise HTTPException(status_code=422, detail="Type de service invalide.")

    city, districts = "00", ""
    if p.type == "home":
        if not p.city_id:
            raise HTTPException(status_code=422, detail="Sélectionnez la ville.")
        ok = db.execute(text("SELECT 1 FROM cities WHERE city_id=:i AND city_country_id=:c AND city_is_active=1"), {"i": p.city_id, "c": cid}).first()
        if not ok:
            raise HTTPException(status_code=422, detail="Cette ville n'est pas dans votre pays.")
        ids = list(dict.fromkeys(p.district_ids))
        if not ids:
            raise HTTPException(status_code=422, detail="Sélectionnez au moins un quartier.")
        found = db.execute(text("SELECT district_id FROM district WHERE district_city_id=:c AND district_id IN :i").bindparams(bindparam("i", expanding=True)), {"c": p.city_id, "i": ids}).fetchall()
        if len(found) != len(ids):
            raise HTTPException(status_code=422, detail="Un quartier ne correspond pas à la ville choisie.")
        city, districts = str(p.city_id), ",".join(str(i) for i in ids)

    return {
        "sub": str(p.subcategory_id), "country": str(cid), "city": city, "type": "1" if p.type == "home" else "0", "districts": districts, "title": " ".join(p.title.split()), "desp": p.description.strip(),
        "exp": f"{p.experience_years} years", "subs": json.dumps([{"unit_id": u.unit_id, "price": str(u.price)} for u in p.units]),
        "opts": php_serialize.dumps([{"id": i + 1, "name": o.name.strip(), "price": str(o.price)} for i, o in enumerate(p.options)]),
        "min": min(u.price for u in p.units), "tools": ", ".join(t.strip() for t in p.tools if t.strip())[:500], "notes": p.notes.strip(), "image": ",".join(p.images), "active": "1" if p.is_active else "0",
    }


def _refresh() -> None:
    clear_directory_cache()
    invalidate_home_cache()


def do_create(db: Session, vendor: Apprenant, payload: ServiceIn) -> dict:
    count = db.execute(text("SELECT COUNT(*) FROM services WHERE s_vendor_id=:v AND (s_is_deleted IS NULL OR s_is_deleted NOT IN ('1','true'))"), {"v": str(vendor.id)}).scalar()
    if (count or 0) >= MAX_SERVICES:
        raise HTTPException(status_code=422, detail=f"{MAX_SERVICES} services maximum.")
    v = _values(db, vendor, payload)
    res = db.execute(
        text(
            "INSERT INTO services (s_subcat_id, s_country_id, s_city_id, s_type, s_district_id, s_vendor_id, s_tools_used, s_title, s_desp, s_exp, s_sub_services, s_min_price, s_is_active, "
            "s_image, s_notes, s_options, s_created_at) VALUES (:sub, :country, :city, :type, :districts, :vendor, :tools, :title, :desp, :exp, :subs, :min, :active, :image, :notes, :opts, :now)"
        ),
        {**v, "vendor": str(vendor.id), "now": datetime.utcnow()},
    )
    db.commit()
    _refresh()
    return {"id": res.lastrowid, "is_active": v["active"] == "1"}


def do_update(db: Session, vendor: Apprenant, service_id: int, payload: ServiceIn) -> dict:
    _load(db, vendor, service_id)
    v = _values(db, vendor, payload)
    db.execute(
        text(
            "UPDATE services SET s_subcat_id=:sub, s_country_id=:country, s_city_id=:city, s_type=:type, s_district_id=:districts, s_tools_used=:tools, s_title=:title, s_desp=:desp, s_exp=:exp, "
            "s_sub_services=:subs, s_min_price=:min, s_is_active=:active, s_image=:image, s_notes=:notes, s_options=:opts WHERE s_id=:i AND s_vendor_id=:vendor"
        ),
        {**v, "i": service_id, "vendor": str(vendor.id)},
    )
    db.commit()
    _refresh()
    return {"id": service_id, "is_active": v["active"] == "1"}


def do_delete(db: Session, vendor: Apprenant, service_id: int) -> None:
    """Supprime le service ; s'il a deja ete reserve, il est archive (les reservations gardent leur reference)."""
    r = _load(db, vendor, service_id)
    if int(r[21] or 0) > 0:
        db.execute(text("UPDATE services SET s_is_active='0', s_is_deleted='1' WHERE s_id=:i AND s_vendor_id=:v"), {"i": service_id, "v": str(vendor.id)})
    else:
        db.execute(text("DELETE FROM services WHERE s_id=:i AND s_vendor_id=:v"), {"i": service_id, "v": str(vendor.id)})
    db.commit()
    _refresh()


@router.post("/services", status_code=201)
@limiter.limit("30/minute")
def create_service(request: Request, payload: ServiceIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    return do_create(db, provider, payload)


@router.put("/services/{service_id}")
@limiter.limit("60/minute")
def update_service(request: Request, service_id: int, payload: ServiceIn, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    return do_update(db, provider, service_id, payload)


@router.post("/services/{service_id}/duplicate", status_code=201)
@limiter.limit("20/minute")
def duplicate_service(request: Request, service_id: int, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    """Copie un service (masque) pour en faire une variante, sans tout ressaisir."""
    _load(db, provider, service_id)
    count = db.execute(text("SELECT COUNT(*) FROM services WHERE s_vendor_id=:v AND (s_is_deleted IS NULL OR s_is_deleted NOT IN ('1','true'))"), {"v": str(provider.id)}).scalar()
    if (count or 0) >= MAX_SERVICES:
        raise HTTPException(status_code=422, detail=f"{MAX_SERVICES} services maximum.")
    res = db.execute(
        text(
            "INSERT INTO services (s_subcat_id, s_country_id, s_city_id, s_type, s_district_id, s_vendor_id, s_tools_used, s_title, s_desp, s_exp, s_sub_services, s_min_price, s_is_active, "
            "s_image, s_notes, s_options, s_created_at) SELECT s_subcat_id, s_country_id, s_city_id, s_type, s_district_id, s_vendor_id, s_tools_used, CONCAT(LEFT(s_title, 110), ' (copie)'), "
            "s_desp, s_exp, s_sub_services, s_min_price, '0', s_image, s_notes, s_options, :now FROM services WHERE s_id=:i AND s_vendor_id=:v"
        ),
        {"i": service_id, "v": str(provider.id), "now": datetime.utcnow()},
    )
    db.commit()
    return {"id": res.lastrowid, "is_active": False}


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: int, provider: Apprenant = Depends(get_provider), db: Session = Depends(get_db)):
    do_delete(db, provider, service_id)


@router.post("/services/images", status_code=201)
@limiter.limit("40/minute")
async def upload_service_image(request: Request, file: UploadFile = File(...), provider: Apprenant = Depends(get_provider)):
    """Televerse UNE photo (Cloudinary) et renvoie son URL, a joindre a `images` du service."""
    return {"url": await _image(file)}
