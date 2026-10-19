"""Construction de la reponse agregee de la page d'accueil (GET /home).

Objectifs : UNE seule requete HTTP pour le site, un nombre FIXE de requetes
SQL (pas de N+1, tout en lots), et un cache memoire court invalide des
qu'un admin modifie la configuration.

Sources d'une section, par ordre de priorite :
  1. la configuration enregistree par l'admin (academy_content_sections +
     academy_home_items) ;
  2. a defaut, le contenu par defaut de app.services.home_defaults.
Les sections dynamiques (services, mieux notes, actualites, avis, chiffres)
completent ensuite leur contenu a partir des donnees reelles Trankyl."""
import copy
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.content import ContentSection
from app.models.home import HomeItem
from app.services.countries import active_countries, marketplace_country_id, provider_offer_clause, public_provider_clause
from app.services.home_defaults import SECTION_ORDER, SECTIONS, SERVICE_TONES
from app.services.trust_score import TRUST_SCORE_THRESHOLD



# ---------------------------------------------------------------------------
# Cache memoire (par processus) + invalidation
# ---------------------------------------------------------------------------
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_refreshing: set[tuple[str, str]] = set()
_cache_lock = threading.Lock()
_version = 0
_log = logging.getLogger(__name__)

# Les requetes independantes d'une phase tournent en parallele, chacune sur sa
# propre session/connexion : la latence totale ~ celle de la requete la plus
# lente, pas la somme.
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="home")


def _in_session(fn, *args):
    db = SessionLocal()
    try:
        return fn(db, *args)
    finally:
        db.close()


def invalidate_home_cache() -> None:
    """A appeler apres toute ecriture de configuration d'accueil : vide le
    cache pour que la prochaine lecture reconstruise a partir de la base."""
    global _version
    with _cache_lock:
        _cache.clear()
        _version += 1


def _store(key: tuple[str, str], payload: dict) -> dict:
    payload["version"] = hashlib.md5(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    with _cache_lock:
        _cache[key] = (time.monotonic() + settings.home_cache_ttl_seconds, payload)
    return payload


def _refresh_in_background(key: tuple[str, str]) -> None:
    def work():
        try:
            _store(key, _build_parallel(key[0], key[1]))
        except Exception:  # noqa: BLE001 - le site continue de servir l'ancienne version
            _log.exception("Rafraichissement du cache d'accueil echoue (%s)", key)
        finally:
            with _cache_lock:
                _refreshing.discard(key)

    with _cache_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)
    threading.Thread(target=work, name="home-refresh", daemon=True).start()


def get_home_cached(lang: str, country: str) -> dict:
    """Stale-while-revalidate : une reponse expiree est servie TELLE QUELLE
    pendant qu'un thread la reconstruit, donc aucun visiteur n'attend la base
    sauf le tout premier appel apres un demarrage a froid (voir warm_home_cache)."""
    key = (lang, country)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit:
        if hit[0] <= now:
            _refresh_in_background(key)
        return hit[1]
    return _store(key, _build_parallel(lang, country))


def warm_home_cache() -> None:
    """Prechauffe le cache au demarrage (en arriere-plan) pour les combinaisons
    les plus courantes."""

    def work():
        for lang, country in (("fr", "TG"), ("en", "TG")):
            try:
                _store((lang, country), _build_parallel(lang, country))
            except Exception:  # noqa: BLE001
                _log.exception("Prechauffage du cache d'accueil echoue (%s, %s)", lang, country)

    threading.Thread(target=work, name="home-warm", daemon=True).start()


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def _loads(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _pick(lang: str, fr: str | None, en: str | None) -> str | None:
    if lang == "en" and en:
        return en
    return fr


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith(("http://", "https://", "//", "/")):
        return path
    return settings.media_base_url.rstrip("/") + "/" + path.lstrip("/")


def _fmt_number(n: int) -> str:
    return f"{n:,}".replace(",", " ")  # espace fine insecable


def _split_first(name: str | None) -> str:
    return (name or "").strip().split(" ", 1)[0]


def _item_dict(lang: str, row: HomeItem | dict) -> dict:
    """Normalise un item (ligne SQL ou dict par defaut) vers la forme publique."""
    g = (lambda k: row.get(k)) if isinstance(row, dict) else (lambda k: getattr(row, k, None))
    data = g("data") if isinstance(row, dict) else _loads(g("data_json"))
    return {
        "id": g("id"),
        "kind": g("kind"),
        "title": _pick(lang, g("title"), g("title_en")),
        "subtitle": _pick(lang, g("subtitle"), g("subtitle_en")),
        "body": _pick(lang, g("body"), g("body_en")),
        "icon": g("icon"),
        "image_url": _media_url(g("image_url")),
        "tone": g("tone"),
        "link_url": g("link_url"),
        "ref_type": g("ref_type"),
        "ref_id": g("ref_id"),
        "data": data or {},
    }


# ---------------------------------------------------------------------------
# Lecture de la configuration (2 requetes, quel que soit le nombre de sections)
# ---------------------------------------------------------------------------
def _load_sections(db: Session, country: str) -> dict[str, ContentSection]:
    rows = db.query(ContentSection).filter(ContentSection.key.in_(list(SECTIONS)), ContentSection.country_code == country).all()
    return {r.key: r for r in rows}


def _load_items(db: Session, country: str) -> dict[str, list[HomeItem]]:
    items: dict[str, list[HomeItem]] = {}
    for it in (
        db.query(HomeItem)
        .filter(HomeItem.section_key.in_(list(SECTIONS)), HomeItem.country_code == country)
        .order_by(HomeItem.section_key, HomeItem.sort_order, HomeItem.id)
        .all()
    ):
        items.setdefault(it.section_key, []).append(it)
    return items


def _active_window(it: HomeItem, now: datetime) -> bool:
    if not it.is_active:
        return False
    if it.starts_at and it.starts_at > now:
        return False
    if it.ends_at and it.ends_at < now:
        return False
    return True


# ---------------------------------------------------------------------------
# Resolutions dynamiques
# ---------------------------------------------------------------------------
def _resolve_services(db: Session, lang: str, payload: dict, items: list[dict]) -> list[dict]:
    """Grille de services : items references sur `sub_categories` (nom/image
    lus a la source), ou, en mode "auto" sans item configure, les
    sous-categories actives les plus fournies en prestations. Une seule
    requete dans les deux cas."""
    ref_ids = [i["ref_id"] for i in items if i["ref_type"] == "sub_category" and i["ref_id"]]
    auto_limit = int(payload.get("auto_limit") or 12)
    columns = "sc.subcat_id, sc.subcat_name_fr, sc.subcat_name_en, sc.subcat_desp_fr, sc.subcat_desp_en, sc.subcat_image"

    catalog: dict[int, dict] = {}
    auto_ids: list[int] = []
    if not items and payload.get("mode", "auto") == "auto":
        rows = db.execute(
            text(
                f"SELECT {columns} FROM sub_categories sc "
                "LEFT JOIN (SELECT s_subcat_id, COUNT(*) n FROM services WHERE s_is_active='1' GROUP BY s_subcat_id) s "
                "ON s.s_subcat_id = sc.subcat_id WHERE sc.subcat_is_active=1 "
                "ORDER BY COALESCE(s.n,0) DESC, sc.subcat_id LIMIT :lim"
            ),
            {"lim": auto_limit},
        ).fetchall()
        auto_ids = [r[0] for r in rows]
    elif ref_ids:
        rows = db.execute(
            text(f"SELECT {columns} FROM sub_categories sc WHERE sc.subcat_id IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"ids": ref_ids},
        ).fetchall()
    else:
        rows = []
    for r in rows:
        catalog[r[0]] = {"name": _pick(lang, r[1], r[2]), "desc": _pick(lang, r[3], r[4]), "image": _media_url(r[5])}

    template = payload.get("item_url_template") or "/recherche?q={name}"
    blank = {"kind": "service", "ref_type": "sub_category", "title": None, "subtitle": None, "body": None, "icon": None, "image_url": None, "tone": None, "link_url": None, "id": None, "data": {}}
    source = items if items else [{**blank, "ref_id": i} for i in auto_ids]
    out: list[dict] = []
    for n, it in enumerate(source):
        cat = catalog.get(it["ref_id"]) if it["ref_type"] == "sub_category" else None
        name = it["title"] or (cat["name"] if cat else None)
        if not name:
            continue
        out.append(
            {
                **it,
                "title": name,
                "subtitle": it["subtitle"] or (_short(cat["desc"]) if cat else None),
                "image_url": it["image_url"] or (cat["image"] if cat else None),
                "tone": it["tone"] or SERVICE_TONES[n % len(SERVICE_TONES)],
                "link_url": it["link_url"] or template.replace("{name}", quote(name)),
                "code": _initials(name),
            }
        )
    return out


def _short(text_: str | None, n: int = 40) -> str | None:
    if not text_:
        return None
    t = " ".join(text_.split())
    if len(t) < 3:  # "-" et autres valeurs de remplissage : pas de sous-titre
        return None
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _initials(name: str) -> str:
    letters = [w[0] for w in name.replace("&", " ").split() if w and w[0].isalpha()]
    return (letters[0].upper() + (name.strip()[1:2].lower() if len(letters) < 2 else letters[1].lower())) if letters else "?"


def _resolve_stats(db: Session, lang: str, items: list[dict]) -> list[dict]:
    needed = {i["data"].get("source") for i in items}
    counts: dict[str, int] = {}
    selects = {
        "vendors_total": "SELECT COUNT(*) FROM vendors",
        "certified_total": "SELECT COUNT(*) FROM vendors WHERE vendor_academy_status='certified_provider' AND vendor_academy_verified=1",
        "clients_total": "SELECT COUNT(*) FROM clients",
        "bookings_total": "SELECT COUNT(*) FROM bookings WHERE bk_service_status IS NULL OR bk_service_status NOT IN ('3','4')",
        "countries_served": "SELECT COUNT(*) FROM countries WHERE country_has_service='1'",
    }
    todo = [k for k in selects if k in needed]
    if todo:
        # une seule requete pour tous les compteurs
        sql = "SELECT " + ", ".join(f"({selects[k]}) AS `{k}`" for k in todo)
        row = db.execute(text(sql)).mappings().first()
        counts = {k: int(row[k] or 0) for k in todo}

    out = []
    for it in items:
        d = it["data"]
        src = d.get("source", "manual")
        if src == "manual":
            value = str(d.get("value", ""))
        else:
            n = counts.get(src, 0)
            n = max(n, int(d.get("min", 0)))
            step = int(d.get("round_to") or 0)
            suffix = str(d.get("suffix", ""))
            if step and n >= step:
                n = (n // step) * step  # "5 000+" plutot que 5 219
            elif step:
                suffix = ""  # sous le palier : valeur exacte, sans "+"
            value = _fmt_number(n) + suffix
        out.append({**it, "data": {**d, "value": value}})
    return out


def _resolve_news(db: Session, lang: str, payload: dict) -> list[dict]:
    limit = int(payload.get("limit") or 3)
    rows = db.execute(
        text(
            "SELECT event_id, event_title, event_category, event_image, event_created_at FROM events "
            "WHERE event_is_active=1 ORDER BY event_created_at DESC, event_id DESC LIMIT :lim"
        ),
        {"lim": limit},
    ).fetchall()
    return [{"id": r[0], "title": r[1], "category": r[2], "image_url": _media_url(r[3]), "published_at": r[4].date().isoformat() if r[4] else None, "link_url": f"/blog/{r[0]}"} for r in rows]


def _resolve_testimonials(db: Session, lang: str, payload: dict, manual: list[dict]) -> list[dict]:
    limit = int(payload.get("limit") or 3)
    min_rating = int(payload.get("min_rating") or 1)
    out = [
        {"rating": 5, "text": m["body"] or m["title"], "author": m["subtitle"], "manual": True}
        for m in manual
        if (m["body"] or m["title"])
    ][:limit]
    remaining = limit - len(out)
    if remaining > 0:
        rows = db.execute(
            text(
                "SELECT r.rating, r.comment, c.client_name, v.vendor_address_city, "
                "(SELECT m.nom FROM academy_certifications ce JOIN academy_niveaux n ON n.id=ce.niveau_id JOIN academy_metiers m ON m.id=n.metier_id "
                " WHERE ce.vendor_id=r.vendor_id ORDER BY ce.delivree_at LIMIT 1) AS metier, "
                "(SELECT m.nom_en FROM academy_certifications ce JOIN academy_niveaux n ON n.id=ce.niveau_id JOIN academy_metiers m ON m.id=n.metier_id "
                " WHERE ce.vendor_id=r.vendor_id ORDER BY ce.delivree_at LIMIT 1) AS metier_en "
                "FROM academy_reviews r JOIN clients c ON c.client_id=r.client_id JOIN vendors v ON v.vendor_id=r.vendor_id "
                "WHERE r.status='approved' AND r.rating>=:minr AND r.comment IS NOT NULL AND r.comment<>'' "
                "ORDER BY r.created_at DESC LIMIT :lim"
            ),
            {"minr": min_rating, "lim": remaining},
        ).fetchall()
        for r in rows:
            parts = [p for p in (_split_first(r[2]), r[3], _pick(lang, r[4], r[5])) if p]
            out.append({"rating": int(r[0]), "text": r[1], "author": " · ".join(parts), "manual": False})
    return out


_FIRST_METIER = (
    "(SELECT m.{col} FROM academy_certifications c JOIN academy_niveaux n ON n.id=c.niveau_id "
    "JOIN academy_metiers m ON m.id=n.metier_id WHERE c.vendor_id=v.vendor_id ORDER BY c.delivree_at LIMIT 1)"
)
_NOT_CANCELLED = "(b.bk_service_status IS NULL OR b.bk_service_status NOT IN ('3','4'))"


def _resolve_top_providers(db: Session, lang: str, payload: dict, country: str, pinned_ids: list[int]) -> list[dict]:
    """Prestataires certifies et verifies, classes par : epingles / mis en
    avant, puis note, nombre d'avis, missions, score de confiance. UNE seule
    requete : notes, missions, profil et metier sont des sous-requetes
    correlees (index sur vendor_id partout), sur un ensemble de quelques
    dizaines de candidats."""
    limit = int(payload.get("limit") or 4)
    min_rating = float(payload.get("min_rating") or 0)
    min_reviews = int(payload.get("min_reviews_for_average") or 3)
    fill = bool(payload.get("fill_with_unrated", True))
    country_id = marketplace_country_id(db, country)

    sql = (
        "SELECT v.vendor_id, v.vendor_name, v.vendor_image, v.vendor_address_city, v.vendor_mark, v.vendor_jobs_count, COALESCE(t.score_pct,0) AS score_pct, "
        "(SELECT AVG(r.rating) FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved') AS avg_rating, "
        "(SELECT COUNT(*) FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved') AS n_reviews, "
        f"(SELECT COUNT(*) FROM bookings b WHERE b.bk_vendor_id=v.vendor_id AND {_NOT_CANCELLED}) AS missions, "
        "p.is_insured, p.top_override, p.is_featured, p.featured_order, p.public_slug, p.response_time_minutes, "
        + _FIRST_METIER.format(col="nom") + " AS metier, "
        + _FIRST_METIER.format(col="nom_en") + " AS metier_en "
        "FROM vendors v LEFT JOIN academy_trust_scores t ON t.vendor_id=v.vendor_id "
        "LEFT JOIN academy_provider_profiles p ON p.vendor_id=v.vendor_id "
        "WHERE v.vendor_academy_verified=1 AND ((v.vendor_academy_status='certified_provider' AND t.score_pct>=:thr) OR v.vendor_academy_status='provider')"
    )
    params: dict = {"thr": TRUST_SCORE_THRESHOLD}
    offer, offer_params = public_provider_clause(db, country, "v")  # le pays est porte par les services publies
    sql += f" AND {offer}"
    params.update(offer_params)

    rows = []
    for (vid, name, image, city, mark, jobs, trust, avg, n_reviews, n_missions_db, insured, top_override, featured, featured_order, slug, response_minutes, metier, metier_en) in db.execute(text(sql), params).fetchall():
        n_reviews = int(n_reviews or 0)
        mark = float(mark) if mark else None
        avg = float(avg) if avg is not None else None
        # Moyenne des avis seulement quand elle repose sur assez d'avis ; sinon
        # la note historique du prestataire (vendors.vendor_mark), puis a defaut la moyenne.
        rating = avg if (avg is not None and n_reviews >= min_reviews) else (mark or avg)
        n_missions = max(int(n_missions_db or 0), int(jobs or 0))
        pinned = vid in pinned_ids or bool(featured)
        is_top = bool(top_override) if top_override is not None else bool(rating and rating >= 4.8 and n_missions >= 50)
        rows.append(
            {
                "vendor_id": vid,
                "name": _display_name(name),
                "initials": _person_initials(name),
                "job": _pick(lang, metier, metier_en),
                "city": city,
                "image_url": image if (image and image.startswith("http")) else _media_url(image),
                "rating": round(rating, 1) if rating else None,
                "reviews_count": n_reviews,
                "missions": n_missions,
                "badges": {"verified": True, "certified": metier is not None, "insured": bool(insured), "top": is_top},
                "profile_url": f"/profil/{slug or vid}",
                "response_minutes": response_minutes,
                "_pinned": pinned,
                "_pin_order": pinned_ids.index(vid) if vid in pinned_ids else int(featured_order or 0),
                "_trust": float(trust),
            }
        )

    if min_rating:
        rows = [r for r in rows if r["rating"] and r["rating"] >= min_rating]
    if not fill:
        rows = [r for r in rows if r["rating"] or r["_pinned"]]
    rows.sort(key=lambda r: (not r["_pinned"], r["_pin_order"] if r["_pinned"] else 0, -(r["rating"] or 0), -r["reviews_count"], -r["missions"], -r["_trust"]))
    out = rows[:limit]
    for r in out:
        for k in ("_pinned", "_pin_order", "_trust"):
            r.pop(k, None)
    return out


def _resolve_hero_slides(lang: str, items: list[dict]) -> dict:
    """Affiches du hero : chaque carte est une IMAGE (publiee depuis l'admin) avec, en option,
    une version mobile, un lien, un bouton et une legende. Les affiches sans image sont ignorees ;
    la fenetre de diffusion (debut/fin) et l'activation sont deja appliquees en amont."""
    slides = []
    for n, it in enumerate(items):
        if not it["image_url"]:
            continue
        d = it["data"] or {}
        cta = d.get("cta_label_en") if lang == "en" and d.get("cta_label_en") else d.get("cta_label")
        slides.append(
            {
                "id": f"poster-{it['id'] if it['id'] is not None else n}",
                "image_url": it["image_url"],
                "image_url_mobile": _media_url(d.get("image_mobile")),
                "title": it["title"],
                "subtitle": it["subtitle"],
                "cta_label": cta or None,
                "link_url": it["link_url"],
                # Public vise : "client" | "prestataire" | "both" (les affiches anterieures restent cote client).
                "audience": d.get("audience") if d.get("audience") in ("client", "prestataire", "both") else "client",
            }
        )
    return {"slides": slides}


def _display_name(name: str | None) -> str:
    parts = (name or "").strip().split()
    if len(parts) < 2:
        return parts[0] if parts else ""
    return f"{parts[0]} {parts[1][0].upper()}."


def _person_initials(name: str | None) -> str:
    parts = (name or "").strip().split()
    return "".join(p[0].upper() for p in parts[:2]) or "?"


def _resolve_topbar_countries(db: Session, lang: str, payload: dict) -> dict:
    """Pays de la bande verte. Priorite : pays enregistres dans l'admin
    (Configuration > Pays) ; a defaut, source choisie dans la section `topbar`
    ("db" : pays avec service actif du marketplace, sinon liste "config")."""
    configured = active_countries(db)
    if configured:
        countries = [
            {
                "code": c["code"],
                "name": _pick(lang, c["name"], c["name_en"]),
                "payment_text": _pick(lang, c["payment_text"], c["payment_text_en"]),
                "help_url": c["help_url"],
            }
            for c in configured
        ]
        default = next((c["code"] for c in configured if c["is_default"]), configured[0]["code"])
        return {"countries": countries, "default_country": default}
    if payload.get("countries_source") == "db":
        rows = db.execute(text("SELECT country_code, country_name FROM countries WHERE country_has_service='1' ORDER BY country_name")).fetchall()
        return {"countries": [{"code": r[0], "name": r[1]} for r in rows], "default_country": payload.get("default_country")}
    return {"countries": payload.get("countries", []), "default_country": payload.get("default_country")}


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------
def _build_parallel(lang: str, country: str) -> dict:
    """Phase 1 : sections + cartes (2 requetes en parallele).
    Phase 2 : donnees dynamiques des sections actives (<= 6 requetes en
    parallele). Soit ~2 aller-retours base au total."""
    lang = "en" if lang == "en" else "fr"
    now = datetime.utcnow()

    f_sections = _executor.submit(_in_session, _load_sections, country)
    f_items = _executor.submit(_in_session, _load_items, country)
    persisted, items_by_section = f_sections.result(), f_items.result()

    sections: dict[str, dict] = {}
    order_keys: list[tuple[int, str]] = []
    pending: dict[str, tuple] = {}  # cle de section -> (future, application du resultat)

    for idx, key in enumerate(SECTION_ORDER):
        default = SECTIONS[key]
        row = persisted.get(key)
        if row is not None and not row.is_active:
            continue

        payload = copy.deepcopy(default.get("payload", {}))
        if lang == "en":
            payload = _deep_merge(payload, default.get("payload_en", {}))
        title = _pick(lang, default.get("title"), default.get("title_en"))
        subtitle = _pick(lang, default.get("subtitle"), default.get("subtitle_en"))
        sort_order = idx * 10
        if row is not None:
            payload = _deep_merge(payload, _loads(row.payload_json))
            if lang == "en":
                payload = _deep_merge(payload, _loads(row.payload_json_en))
            title = _pick(lang, row.title or title, row.title_en) or title
            subtitle = _pick(lang, row.subtitle or subtitle, row.subtitle_en) or subtitle
            sort_order = row.sort_order if row.sort_order else sort_order

        db_items = items_by_section.get(key)
        if db_items is not None:  # l'admin a pris la main : ses items remplacent les defauts
            items = [_item_dict(lang, it) for it in db_items if _active_window(it, now)]
        else:
            items = [_item_dict(lang, it) for it in default.get("items", [])]

        section: dict = {"key": key, "type": default["type"], "title": title, "subtitle": subtitle, "payload": payload, "items": items}
        sections[key] = section
        order_keys.append((sort_order, key))

        if key == "topbar":
            pending[key] = (_executor.submit(_in_session, _resolve_topbar_countries, lang, payload), lambda sec, res: sec.update(data=res))
        elif key == "services":
            pending[key] = (_executor.submit(_in_session, _resolve_services, lang, payload, items), lambda sec, res: sec.update(items=res))
        elif key == "stats":
            pending[key] = (_executor.submit(_in_session, _resolve_stats, lang, items), lambda sec, res: sec.update(items=res))
        elif key == "top_providers":
            pinned = [i["ref_id"] for i in items if i["ref_type"] == "vendor" and i["ref_id"]]
            pending[key] = (_executor.submit(_in_session, _resolve_top_providers, lang, payload, country, pinned), lambda sec, res: sec.update(data={"providers": res}))
        elif key == "hero_slides":
            section["data"] = _resolve_hero_slides(lang, items)  # sans requete : tout vient de la configuration
        elif key == "news":
            pending[key] = (_executor.submit(_in_session, _resolve_news, lang, payload), lambda sec, res: sec.update(data={"articles": res}))
        elif key == "testimonials":
            pending[key] = (_executor.submit(_in_session, _resolve_testimonials, lang, payload, items), lambda sec, res: sec.update(data={"reviews": res}))

    for key, (future, apply) in pending.items():
        try:
            apply(sections[key], future.result())
        except Exception:  # noqa: BLE001 - une section en erreur ne doit pas faire tomber l'accueil
            _log.exception("Section d'accueil '%s' indisponible", key)
            sections[key]["data"] = {}
            if key in ("services", "stats"):
                sections[key]["items"] = []

    order_keys.sort()
    return {"lang": lang, "country": country, "order": [k for _, k in order_keys], "sections": sections}
