"""Configuration du site depuis l'admin (menu Configuration).

Premiere rubrique : les pays (bande verte du site, filtrage des prestataires).
Tout est ADDITIF : la table `academy_countries` est vide au depart et le site
conserve son comportement actuel tant qu'aucun pays n'y est enregistre."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam, func, text
from sqlalchemy.orm import Session

from app.api.v1.endpoints.directory import clear_directory_cache
from app.api.deps import forbidden, get_admin_ctx, require_access
from app.db.session import get_db
from app.models.country import Country
from app.schemas.country import CountryIn, CountryOut, CountryReorder, MarketplaceCountry
from app.services.countries import invalidate_countries_cache
from app.services.home import invalidate_home_cache

router = APIRouter(dependencies=[Depends(require_access("config"))])

DEFAULT_COUNTRIES = [
    {"code": "TG", "name": "Togo", "name_en": "Togo", "marketplace_country_id": 217, "calling_code": "228", "currency_code": "XOF", "payment_text": "Paiement : Mixx by Yas · Flooz · Carte", "payment_text_en": "Payment: Mixx by Yas · Flooz · Card", "is_default": True},
    {"code": "CI", "name": "Côte d'Ivoire", "name_en": "Côte d'Ivoire", "marketplace_country_id": 52, "calling_code": "225", "currency_code": "XOF", "payment_text": None, "payment_text_en": None, "is_default": False},
    {"code": "BJ", "name": "Bénin", "name_en": "Benin", "marketplace_country_id": 23, "calling_code": "229", "currency_code": "XOF", "payment_text": None, "payment_text_en": None, "is_default": False},
]


def _need_all_countries(admin) -> None:
    """Creer / supprimer / reordonner les pays touche tout le site : reserve a qui a acces a tous les pays."""
    if not (admin.access.is_super or admin.access.all_countries):
        raise HTTPException(status_code=403, detail="Seul un administrateur ayant accès à tous les pays peut faire cette opération.", headers={"X-Missing-Permission": "all_countries"})


def _changed() -> None:
    invalidate_countries_cache()
    invalidate_home_cache()
    clear_directory_cache()


def _marketplace_names(db: Session, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = db.execute(text("SELECT country_id, country_name FROM countries WHERE country_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": list(ids)}).fetchall()
    return {r[0]: r[1] for r in rows}


def _out(rows: list[Country], db: Session) -> list[CountryOut]:
    names = _marketplace_names(db, {r.marketplace_country_id for r in rows if r.marketplace_country_id})
    out = []
    for r in rows:
        o = CountryOut.model_validate(r)
        o.marketplace_country_name = names.get(r.marketplace_country_id) if r.marketplace_country_id else None
        out.append(o)
    return out


def _check_marketplace(db: Session, mid: int | None) -> None:
    if mid is None:
        return
    if not db.execute(text("SELECT 1 FROM countries WHERE country_id=:i"), {"i": mid}).first():
        raise HTTPException(status_code=400, detail="Pays du marketplace introuvable")


def _set_default(db: Session, keep: Country) -> None:
    """Un seul pays par defaut : on retire le drapeau aux autres."""
    db.query(Country).filter(Country.id != keep.id, Country.is_default.is_(True)).update({Country.is_default: False})


@router.get("/countries", response_model=list[CountryOut])
def list_countries(admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Les pays auxquels l'administrateur a acces (tous pour un super-administrateur)."""
    rows = [c for c in db.query(Country).order_by(Country.sort_order, Country.name).all() if admin.access.in_country(c.code)]
    return _out(rows, db)


@router.get("/countries/marketplace", response_model=list[MarketplaceCountry])
def marketplace_countries(q: str = "", db: Session = Depends(get_db)):
    """Pays du marketplace Trankyl (lecture seule) pour relier un pays Academy."""
    rows = db.execute(
        text(
            "SELECT country_id, country_name, country_code, country_calling_codes, country_has_service FROM countries "
            "WHERE (:q='' OR country_name LIKE :like OR country_code LIKE :like) "
            "ORDER BY (country_has_service='1') DESC, country_name LIMIT 300"
        ),
        {"q": q, "like": f"%{q}%"},
    ).fetchall()
    return [MarketplaceCountry(id=r[0], name=r[1], code=r[2], calling_code=r[3], has_service=(r[4] == "1")) for r in rows]


@router.post("/countries", response_model=CountryOut, status_code=201)
def create_country(payload: CountryIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _need_all_countries(admin)
    if db.query(Country).filter(Country.code == payload.code).first():
        raise HTTPException(status_code=400, detail=f"Le pays {payload.code} existe deja")
    _check_marketplace(db, payload.marketplace_country_id)
    data = payload.model_dump()
    sort_order = data.pop("sort_order")
    country = Country(**data)
    if sort_order is None:  # non precise : en derniere position
        sort_order = (db.query(func.max(Country.sort_order)).scalar() or 0) + 10
    country.sort_order = sort_order
    db.add(country)
    db.flush()
    if country.is_default:
        _set_default(db, country)
    elif not db.query(Country).filter(Country.id != country.id, Country.is_default.is_(True)).first():
        country.is_default = True  # le premier pays enregistre devient le pays par defaut
    db.commit()
    db.refresh(country)
    _changed()
    return _out([country], db)[0]


@router.put("/countries/{country_id}", response_model=CountryOut)
def update_country(country_id: int, payload: CountryIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    country = db.get(Country, country_id)
    if not country or not admin.access.in_country(country.code):
        raise HTTPException(status_code=404, detail="Pays introuvable")
    if payload.code != country.code or bool(payload.is_default) != bool(country.is_default):
        _need_all_countries(admin)  # le code et le pays par defaut concernent tout le site
    if db.query(Country).filter(Country.code == payload.code, Country.id != country_id).first():
        raise HTTPException(status_code=400, detail=f"Le pays {payload.code} existe deja")
    _check_marketplace(db, payload.marketplace_country_id)
    data = payload.model_dump()
    sort_order = data.pop("sort_order")
    for field, value in data.items():
        setattr(country, field, value)
    if sort_order is not None:
        country.sort_order = sort_order
    if country.is_default:
        _set_default(db, country)
    elif not db.query(Country).filter(Country.id != country.id, Country.is_default.is_(True)).first():
        raise HTTPException(status_code=400, detail="Un pays par defaut est requis : definissez-en un autre avant de retirer celui-ci")
    db.commit()
    db.refresh(country)
    _changed()
    return _out([country], db)[0]


@router.delete("/countries/{country_id}", status_code=204)
def delete_country(country_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _need_all_countries(admin)
    country = db.get(Country, country_id)
    if not country:
        raise HTTPException(status_code=404, detail="Pays introuvable")
    others = db.query(Country).filter(Country.id != country_id).order_by(Country.sort_order).all()
    was_default = country.is_default
    db.delete(country)
    if was_default and others:  # le pays par defaut disparait : le suivant prend le relais
        others[0].is_default = True
    db.commit()
    _changed()


@router.post("/countries/reorder")
def reorder_countries(payload: CountryReorder, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _need_all_countries(admin)
    rows = {c.id: c for c in db.query(Country).all()}
    for n, cid in enumerate(payload.ids):
        if cid in rows:
            rows[cid].sort_order = (n + 1) * 10
    db.commit()
    _changed()
    return {"ok": True}


@router.post("/countries/initialize", response_model=list[CountryOut])
def initialize_countries(admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _need_all_countries(admin)
    """Enregistre les pays historiques du site (Togo, Cote d'Ivoire, Benin).
    Idempotent : n'ajoute que ceux qui manquent et ne modifie jamais l'existant."""
    existing = {c.code for c in db.query(Country).all()}
    has_default = db.query(Country).filter(Country.is_default.is_(True)).first() is not None
    for n, d in enumerate(DEFAULT_COUNTRIES):
        if d["code"] in existing:
            continue
        row = Country(**{**d, "is_default": d["is_default"] and not has_default, "is_active": True, "sort_order": (n + 1) * 10})
        # on ne relie a un pays du marketplace que s'il existe vraiment dans cette base
        if row.marketplace_country_id and not db.execute(text("SELECT 1 FROM countries WHERE country_id=:i"), {"i": row.marketplace_country_id}).first():
            row.marketplace_country_id = None
        db.add(row)
    db.commit()
    _changed()
    return _out(db.query(Country).order_by(Country.sort_order, Country.name).all(), db)
