"""Page d'accueil : lecture publique agregee (1 requete, cache + ETag) et
administration de sa configuration (sections, cartes, ordre)."""
import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.deps import current_country, current_lang, forbidden, get_admin_ctx, require_access
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.content import ContentSection
from app.models.home import HomeItem
from app.schemas.home import (
    HomeItemAdminOut,
    HomeItemCreate,
    HomeItemIn,
    HomeSectionAdminOut,
    HomeSectionIn,
    ReorderIn,
    SectionsOrderIn,
)
from app.services.countries import provider_offer_clause
from app.services.home import _loads, get_home_cached, invalidate_home_cache
from app.services.home_defaults import SECTION_ORDER, SECTIONS
from app.services.image_upload import ImageUploadError, upload_image

router = APIRouter()


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
@router.get("")
def get_home(request: Request, response: Response, lang: str = Depends(current_lang), country: str = Depends(current_country)):
    """Tout ce qu'il faut pour afficher l'accueil, en une seule reponse.
    `lang` : fr | en. `country` : code pays (TG, BJ, CI...). Mis en cache
    cote serveur (TTL court, invalide a chaque edition admin) et cote
    navigateur/CDN via ETag + Cache-Control."""
    payload = get_home_cached(lang, country)
    etag = f'W/"{payload["version"]}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=30, stale-while-revalidate=120"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


# ---------------------------------------------------------------------------
# Admin : lecture de la configuration
# ---------------------------------------------------------------------------
def _item_admin(key: str, it: HomeItem | dict) -> HomeItemAdminOut:
    g = (lambda k: it.get(k)) if isinstance(it, dict) else (lambda k: getattr(it, k, None))
    data = g("data") if isinstance(it, dict) else _loads(g("data_json"))
    return HomeItemAdminOut(
        id=None if isinstance(it, dict) else it.id,
        section_key=key,
        kind=g("kind"),
        sort_order=g("sort_order") or 0,
        is_active=True if isinstance(it, dict) else bool(it.is_active),
        title=g("title"),
        title_en=g("title_en"),
        subtitle=g("subtitle"),
        subtitle_en=g("subtitle_en"),
        body=g("body"),
        body_en=g("body_en"),
        icon=g("icon"),
        image_url=g("image_url"),
        tone=g("tone"),
        link_url=g("link_url"),
        ref_type=g("ref_type"),
        ref_id=g("ref_id"),
        data=data or {},
        starts_at=g("starts_at"),
        ends_at=g("ends_at"),
    )


def _section_admin(key: str, row: ContentSection | None, items: list[HomeItem] | None) -> HomeSectionAdminOut:
    default = SECTIONS[key]
    base_payload = default.get("payload", {})
    base_payload_en = default.get("payload_en", {})
    if items is not None:
        shown = [_item_admin(key, i) for i in items]
    else:
        shown = [_item_admin(key, {**i, "sort_order": n * 10}) for n, i in enumerate(default.get("items", []))]
    return HomeSectionAdminOut(
        key=key,
        type=default["type"],
        persisted=row is not None,
        items_persisted=items is not None,
        title=(row.title if row is not None and row.title else default.get("title")),
        title_en=(row.title_en if row is not None and row.title_en else default.get("title_en")),
        subtitle=(row.subtitle if row is not None and row.subtitle else default.get("subtitle")),
        subtitle_en=(row.subtitle_en if row is not None and row.subtitle_en else default.get("subtitle_en")),
        payload={**base_payload, **_loads(row.payload_json)} if row is not None else dict(base_payload),
        payload_en={**base_payload_en, **_loads(row.payload_json_en)} if row is not None else dict(base_payload_en),
        is_active=True if row is None else bool(row.is_active),
        sort_order=(row.sort_order if row is not None and row.sort_order else SECTION_ORDER.index(key) * 10),
        items=shown,
    )


@router.get("/admin/config", response_model=list[HomeSectionAdminOut])
def admin_config(admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    rows = {r.key: r for r in db.query(ContentSection).filter(ContentSection.key.in_(list(SECTIONS)), ContentSection.country_code == admin.country).all()}
    items: dict[str, list[HomeItem]] = {}
    for it in db.query(HomeItem).filter(HomeItem.section_key.in_(list(SECTIONS)), HomeItem.country_code == admin.country).order_by(HomeItem.sort_order, HomeItem.id).all():
        items.setdefault(it.section_key, []).append(it)
    allowed = [k for k in SECTION_ORDER if admin.access.has(f"academy.{_menu_for(k)}.view")]
    if not allowed:
        raise forbidden("academy.home.view")
    out = [_section_admin(k, rows.get(k), items.get(k)) for k in allowed]
    out.sort(key=lambda s: s.sort_order)
    return out


# ---------------------------------------------------------------------------
# Admin : ecriture
# ---------------------------------------------------------------------------
POSTERS_SECTION = "hero_slides"  # les affiches ont leur propre menu et leurs propres permissions


def _menu_for(key: str) -> str:
    return "posters" if key == POSTERS_SECTION else "home"


def _need(admin, key: str, write: bool) -> None:
    """Permission requise selon la section visee : affiches -> `posters`, autres -> `home`."""
    perm = f"academy.{_menu_for(key)}.{'manage' if write else 'view'}"
    if not admin.access.has(perm):
        raise forbidden(perm)


def _check_key(key: str) -> None:
    if key not in SECTIONS:
        raise HTTPException(status_code=404, detail=f"Section inconnue : {key}")


def _upsert_section(db: Session, key: str, payload: HomeSectionIn, country: str) -> ContentSection:
    row = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.country_code == country).first()
    if row is None:
        row = ContentSection(key=key, country_code=country, title="", is_active=True)
        db.add(row)
    row.title = payload.title or ""
    row.title_en = payload.title_en
    row.subtitle = payload.subtitle
    row.subtitle_en = payload.subtitle_en
    row.is_active = payload.is_active
    row.section_type = SECTIONS[key]["type"]
    row.sort_order = payload.sort_order
    row.payload_json = json.dumps(payload.payload, ensure_ascii=False)
    row.payload_json_en = json.dumps(payload.payload_en, ensure_ascii=False)
    return row


def _apply_item(it: HomeItem, p: HomeItemIn) -> None:
    for f in ("kind", "sort_order", "is_active", "title", "title_en", "subtitle", "subtitle_en", "body", "body_en", "icon", "image_url", "tone", "link_url", "ref_type", "ref_id", "starts_at", "ends_at"):
        setattr(it, f, getattr(p, f))
    it.data_json = json.dumps(p.data, ensure_ascii=False) if p.data else None


def _seed_default_items(db: Session, key: str, country: str) -> None:
    """Copie les cartes par defaut en base pour que l'admin PARTE d'elles
    (au lieu de les voir disparaitre des qu'il en ajoute une)."""
    for n, d in enumerate(SECTIONS[key].get("items", [])):
        it = HomeItem(section_key=key, country_code=country)
        _apply_item(it, HomeItemIn(**{**d, "sort_order": n * 10}))
        db.add(it)


def _has_items(db: Session, key: str, country: str) -> bool:
    return db.query(HomeItem.id).filter(HomeItem.section_key == key, HomeItem.country_code == country).first() is not None


def _items_of(db: Session, key: str, country: str) -> list[HomeItem]:
    return db.query(HomeItem).filter(HomeItem.section_key == key, HomeItem.country_code == country).order_by(HomeItem.sort_order, HomeItem.id).all()


def _own_item(db: Session, item_id: int, country: str) -> HomeItem:
    """Un element n'est visible / modifiable que dans son pays."""
    it = db.get(HomeItem, item_id)
    if not it or it.country_code != country:
        raise HTTPException(status_code=404, detail="Element introuvable")
    return it


@router.put("/admin/sections/{key}", response_model=HomeSectionAdminOut)
def admin_put_section(key: str, payload: HomeSectionIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _check_key(key)
    _need(admin, key, True)
    row = _upsert_section(db, key, payload, admin.country)
    db.commit()
    invalidate_home_cache()
    return _section_admin(key, row, _items_of(db, key, admin.country) or None)


@router.post("/admin/sections/{key}/initialize", response_model=HomeSectionAdminOut)
def admin_initialize_section(key: str, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    """Enregistre en base le contenu par defaut d'une section (idempotent :
    ne touche pas a ce qui existe deja)."""
    _check_key(key)
    _need(admin, key, True)
    row = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.country_code == admin.country).first()
    if row is None:
        default = SECTIONS[key]
        row = _upsert_section(
            db,
            key,
            HomeSectionIn(
                title=default.get("title"),
                title_en=default.get("title_en"),
                subtitle=default.get("subtitle"),
                subtitle_en=default.get("subtitle_en"),
                payload=default.get("payload", {}),
                payload_en=default.get("payload_en", {}),
                sort_order=SECTION_ORDER.index(key) * 10,
            ),
            admin.country,
        )
    if not _has_items(db, key, admin.country):
        _seed_default_items(db, key, admin.country)
    db.commit()
    invalidate_home_cache()
    return _section_admin(key, row, _items_of(db, key, admin.country) or None)


@router.post("/admin/sections-order")
def admin_sections_order(payload: SectionsOrderIn, admin=Depends(require_access("home")), db: Session = Depends(get_db)):
    """Reordonne les sections de l'accueil. Les sections non encore
    enregistrees sont creees avec leur contenu par defaut."""
    unknown = [k for k in payload.keys if k not in SECTIONS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Sections inconnues : {unknown}")
    for n, key in enumerate(payload.keys):
        row = db.query(ContentSection).filter(ContentSection.key == key, ContentSection.country_code == admin.country).first()
        if row is None:
            default = SECTIONS[key]
            row = _upsert_section(db, key, HomeSectionIn(title=default.get("title"), title_en=default.get("title_en"), subtitle=default.get("subtitle"), subtitle_en=default.get("subtitle_en"), payload=default.get("payload", {}), payload_en=default.get("payload_en", {})), admin.country)
        row.sort_order = (n + 1) * 10
    db.commit()
    invalidate_home_cache()
    return {"ok": True}


@router.post("/admin/items", response_model=HomeItemAdminOut, status_code=201)
def admin_create_item(payload: HomeItemCreate, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _check_key(payload.section_key)
    _need(admin, payload.section_key, True)
    if not _has_items(db, payload.section_key, admin.country):
        _seed_default_items(db, payload.section_key, admin.country)
        db.flush()  # autoflush desactive : sans cela le MAX ci-dessous ignore les cartes copiees
    it = HomeItem(section_key=payload.section_key, country_code=admin.country)
    _apply_item(it, payload)
    if not payload.sort_order:  # non precise : la nouvelle carte arrive en derniere position
        last = db.query(func.max(HomeItem.sort_order)).filter(HomeItem.section_key == payload.section_key, HomeItem.country_code == admin.country).scalar()
        it.sort_order = (last or 0) + 10
    db.add(it)
    db.commit()
    db.refresh(it)
    invalidate_home_cache()
    return _item_admin(payload.section_key, it)


@router.put("/admin/items/{item_id}", response_model=HomeItemAdminOut)
def admin_update_item(item_id: int, payload: HomeItemIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    it = _own_item(db, item_id, admin.country)
    _need(admin, it.section_key, True)
    _apply_item(it, payload)
    db.commit()
    db.refresh(it)
    invalidate_home_cache()
    return _item_admin(it.section_key, it)


@router.delete("/admin/items/{item_id}", status_code=204)
def admin_delete_item(item_id: int, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    it = _own_item(db, item_id, admin.country)
    _need(admin, it.section_key, True)
    db.delete(it)
    db.commit()
    invalidate_home_cache()


@router.post("/admin/sections/{key}/reorder")
def admin_reorder_items(key: str, payload: ReorderIn, admin=Depends(get_admin_ctx), db: Session = Depends(get_db)):
    _check_key(key)
    _need(admin, key, True)
    items = {i.id: i for i in db.query(HomeItem).filter(HomeItem.section_key == key, HomeItem.country_code == admin.country).all()}
    for n, item_id in enumerate(payload.ids):
        if item_id in items:
            items[item_id].sort_order = (n + 1) * 10
    db.commit()
    invalidate_home_cache()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin : selecteurs (pour lier une carte a une donnee existante)
# ---------------------------------------------------------------------------
@router.get("/admin/catalog/sub-categories", dependencies=[Depends(require_access("home"))])
def admin_catalog(q: str = "", limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT sc.subcat_id, sc.subcat_name_fr, sc.subcat_name_en, c.cat_name_fr FROM sub_categories sc "
            "LEFT JOIN categories c ON c.cat_id=sc.subcat_cat_id WHERE sc.subcat_is_active=1 "
            "AND (:q='' OR sc.subcat_name_fr LIKE :like OR sc.subcat_name_en LIKE :like) ORDER BY sc.subcat_name_fr LIMIT :lim"
        ),
        {"q": q, "like": f"%{q}%", "lim": min(limit, 200)},
    ).fetchall()
    return [{"id": r[0], "name": r[1], "name_en": r[2], "category": r[3]} for r in rows]


@router.get("/admin/catalog/providers")
def admin_catalog_providers(q: str = "", limit: int = 30, admin=Depends(require_access("home")), db: Session = Depends(get_db)):
    offer, offer_params = provider_offer_clause(db, admin.country, "v")  # prestataires visibles dans ce pays (services publies)
    rows = db.execute(
        text(
            "SELECT v.vendor_id, v.vendor_name, v.vendor_address_city FROM vendors v WHERE v.vendor_academy_status IN ('certified_provider','provider') "
            f"AND (:q='' OR v.vendor_name LIKE :like) AND {offer} ORDER BY v.vendor_name LIMIT :lim"
        ),
        {"q": q, "like": f"%{q}%", "lim": min(limit, 100), **offer_params},
    ).fetchall()
    return [{"id": r[0], "name": r[1], "city": r[2]} for r in rows]


@router.post("/admin/upload-image")
@limiter.limit("30/minute")
async def admin_upload_image(request: Request, file: UploadFile = File(...), admin=Depends(get_admin_ctx)):
    """Envoie une affiche / une image du site vers Cloudinary et retourne son URL publique."""
    if not (admin.access.has("academy.posters.manage") or admin.access.has("academy.home.manage")):
        raise forbidden("academy.posters.manage")
    content = await file.read()
    try:
        url = upload_image(content, file.content_type or "")
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"url": url}
