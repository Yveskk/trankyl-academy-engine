"""Annuaire public des prestataires : recherche, localites, profil.
Lecture seule, sans authentification (donnees deja publiques sur le site)."""
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import current_country, current_lang
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.services.countries import service_country_clause
from app.services.home import _media_url, _pick, _short
from app.services.provider_profile import build_profile, build_services
from app.services.search import SORTS, list_locations, search_providers

router = APIRouter()

# Petit cache memoire (20 s) : une meme recherche repetee (pagination, retour
# arriere, plusieurs visiteurs sur la meme requete) ne retouche pas la base.
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()
_TTL = 20
_MAX = 500


def _cached(key: tuple, build):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _lock:
        if len(_cache) >= _MAX:
            _cache.clear()
        _cache[key] = (now + _TTL, value)
    return value


@router.get("/search")
@limiter.limit("120/minute")
def search(
    request: Request,
    q: str = Query("", max_length=300),
    subcategory_id: int | None = None,
    country: str = Depends(current_country),
    city: str | None = Query(None, max_length=100),
    district: str | None = Query(None, max_length=100),
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    availability: str | None = Query(None, pattern="^(today|tomorrow|weekend)$"),
    min_rating: float = Query(0, ge=0, le=5),
    identity: bool = False,
    certified: bool = False,
    insured: bool = False,
    top: bool = False,
    languages: str = Query("", max_length=200, description="Liste separee par des virgules"),
    sort: str = "recommended",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    lang: str = Depends(current_lang),
    db: Session = Depends(get_db),
):
    if sort not in SORTS:
        raise HTTPException(status_code=400, detail=f"sort doit etre l'un de : {sorted(SORTS)}")
    langs = [x.strip() for x in languages.split(",") if x.strip()]
    key = ("search", q.strip().lower(), subcategory_id, country.upper(), city, district, lat, lng, availability, min_rating, identity, certified, insured, top, tuple(langs), sort, limit, offset, lang)
    return _cached(
        key,
        lambda: search_providers(
            db, q=q, subcategory_id=subcategory_id, country=country, city=city, district=district, lat=lat, lng=lng,
            availability=availability, min_rating=min_rating, identity=identity, certified=certified, insured=insured, top=top,
            languages=langs, sort=sort, limit=limit, offset=offset, lang=lang,
        ),
    )


@router.get("/categories")
def categories(lang: str = Depends(current_lang), db: Session = Depends(get_db)):
    """Metiers proposes a l'inscription d'un prestataire (catalogue de services de Trankyl)."""

    def build():
        rows = db.execute(text("SELECT subcat_id, subcat_name_fr, subcat_name_en FROM sub_categories WHERE subcat_is_active=1 ORDER BY subcat_name_fr")).fetchall()
        return {"categories": [{"id": r[0], "name": (r[2] if lang == "en" and r[2] else r[1])} for r in rows]}

    return _cached(("cats", lang), build)


@router.get("/catalog")
def catalog(country: str = Depends(current_country), lang: str = Depends(current_lang), db: Session = Depends(get_db)):
    """Catalogue complet des metiers (page "Toutes les categories") : nom, description, image et nombre
    de prestataires verifies qui les proposent dans le pays. UNE requete groupee, cache memoire."""

    def build():
        s_clause, s_params = service_country_clause(db, country, "s")
        rows = db.execute(
            text(
                "SELECT sc.subcat_id, sc.subcat_name_fr, sc.subcat_name_en, sc.subcat_desp_fr, sc.subcat_desp_en, sc.subcat_image, "
                "COALESCE(p.n, 0), COALESCE(p.v, 0) FROM sub_categories sc "
                "LEFT JOIN (SELECT s.s_subcat_id AS sid, COUNT(*) AS n, COUNT(DISTINCT s.s_vendor_id) AS v "
                "FROM services s JOIN vendors v ON v.vendor_id = s.s_vendor_id AND v.vendor_academy_verified = 1 "
                f"WHERE s.s_is_active = '1' AND {s_clause} GROUP BY s.s_subcat_id) p ON p.sid = sc.subcat_id "
                "WHERE sc.subcat_is_active = 1 ORDER BY sc.subcat_name_fr"
            ),
            s_params,
        ).fetchall()
        items = []
        for r in rows:
            name = _pick(lang, r[1], r[2])
            if not name:
                continue
            items.append({"id": r[0], "name": name, "description": _short(_pick(lang, r[3], r[4]), 90), "image_url": _media_url(r[5]), "providers": int(r[7]), "services": int(r[6])})
        return {"total": len(items), "items": items}

    return _cached(("catalog", country.upper(), lang), build)


@router.get("/locations")
def locations(country: str = Depends(current_country), db: Session = Depends(get_db)):
    return _cached(("loc", country.upper()), lambda: {"locations": list_locations(db, country)})


@router.get("/providers/{ref}")
@limiter.limit("120/minute")
def provider_profile(request: Request, ref: str, lang: str = Depends(current_lang), country: str = Depends(current_country), reviews_limit: int = Query(10, ge=0, le=50), db: Session = Depends(get_db)):
    profile = _cached(("profile", ref.lower(), lang, country, reviews_limit), lambda: build_profile(db, ref, lang, reviews_limit, country))
    if profile is None:
        raise HTTPException(status_code=404, detail="Prestataire introuvable")
    return profile


@router.get("/providers/{ref}/services")
@limiter.limit("120/minute")
def provider_services(request: Request, ref: str, lang: str = Depends(current_lang), country: str = Depends(current_country), db: Session = Depends(get_db)):
    """Services detailles d'un prestataire (page Reserver)."""
    data = _cached(("services", ref.lower(), lang, country), lambda: build_services(db, ref, lang, country))
    if data is None:
        raise HTTPException(status_code=404, detail="Prestataire introuvable")
    return data


def clear_directory_cache() -> None:
    with _lock:
        _cache.clear()
