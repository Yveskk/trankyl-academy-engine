"""Page profil public d'un prestataire (GET /directory/providers/{ref}).

Lecture seule, en un nombre fixe de requetes. Seuls les prestataires
ELIGIBLES (certifies, verifies, score de confiance >= seuil) sont publics :
la meme regle que la recherche et le matching."""
import json
import re
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.provider import ProviderProfile
from app.services.search import (
    _NOT_CANCELLED,
    compute_slots,
    display_name,
    initials,
    is_top,
    load_availability,
    local_now,
    parse_languages,
    rating_of,
    slot_label,
)
from app.services import php_serialize
from app.services.countries import provider_offer_clause, public_provider_clause, service_country_clause
from app.services.trust_score import TRUST_SCORE_THRESHOLD


def resolve_vendor_id(db: Session, ref: str) -> int | None:
    """`ref` : slug public, identifiant numerique, ou "<texte>-<id>"."""
    ref = (ref or "").strip().lower()
    if not ref:
        return None
    row = db.query(ProviderProfile.vendor_id).filter(ProviderProfile.public_slug == ref).first()
    if row:
        return row[0]
    if ref.isdigit():
        return int(ref)
    m = re.search(r"-(\d+)$", ref)
    return int(m.group(1)) if m else None


def _districts(db: Session, raw: str | None) -> list[str]:
    """`vendor_working_district` : selon l'origine, noms separes par des virgules,
    liste JSON, ou identifiants de quartiers (table `district`)."""
    if not raw:
        return []
    raw = raw.strip()
    values: list = []
    try:
        parsed = json.loads(raw)
        values = parsed if isinstance(parsed, list) else [parsed]
    except ValueError:
        values = [p.strip() for p in re.split(r"[,;|]", raw) if p.strip()]
    ids = [int(v) for v in values if str(v).isdigit()]
    names = [str(v) for v in values if not str(v).isdigit()]
    if ids:
        rows = db.execute(text("SELECT district_name FROM district WHERE district_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids}).fetchall()
        names += [r[0] for r in rows]
    return names[:12]


def build_profile(db: Session, ref: str, lang: str = "fr", reviews_limit: int = 10, country: str = "TG") -> dict | None:
    """Profil public DANS CE PAYS : seuls les services publies dans ce pays sont montres, et un prestataire qui n'y
    publie rien (et n'y est pas inscrit) y est introuvable."""
    lang = "en" if lang == "en" else "fr"
    vid = resolve_vendor_id(db, ref)
    if vid is None:
        return None
    offer, offer_params = public_provider_clause(db, country, "v")
    s_clause, s_params = service_country_clause(db, country, "services")

    v = db.execute(
        text(
            "SELECT v.vendor_id, v.vendor_name, v.vendor_image, v.vendor_bio, v.vendor_address_city, v.vendor_working_district, v.vendor_latitude, v.vendor_longitude, "
            "v.vendor_mark, v.vendor_jobs_count, v.vendor_local_languages, v.vendor_sign_up_at, v.vendor_created_at, COALESCE(t.score_pct,0) AS score_pct, "
            "(SELECT AVG(r.rating) FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved') AS avg_rating, "
            "(SELECT COUNT(*) FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved') AS n_reviews, "
            f"(SELECT COUNT(*) FROM bookings b WHERE b.bk_vendor_id=v.vendor_id AND {_NOT_CANCELLED}) AS missions "
            "FROM vendors v LEFT JOIN academy_trust_scores t ON t.vendor_id=v.vendor_id "
            "WHERE v.vendor_id=:id AND v.vendor_academy_verified=1 AND ((v.vendor_academy_status='certified_provider' AND t.score_pct>=:thr) OR v.vendor_academy_status='provider') "
            f"AND {offer}"
        ),
        {"id": vid, "thr": TRUST_SCORE_THRESHOLD, **offer_params},
    ).mappings().first()
    if not v:
        return None

    p = db.query(ProviderProfile).filter(ProviderProfile.vendor_id == vid).first()
    now = local_now()

    services = db.execute(
        text(
            f"SELECT s_title, s_desp, s_min_price, s_id FROM services WHERE s_vendor_id=:id AND s_is_active='1' AND {s_clause} "
            "ORDER BY (s_min_price IS NULL OR s_min_price=0), s_min_price, s_id LIMIT 30"
        ),
        {"id": vid, **s_params},
    ).fetchall()

    certs = db.execute(
        text(
            "SELECT m.nom, m.nom_en, n.numero, n.nom, n.nom_en, c.delivree_at FROM academy_certifications c "
            "JOIN academy_niveaux n ON n.id=c.niveau_id JOIN academy_metiers m ON m.id=n.metier_id WHERE c.vendor_id=:id ORDER BY c.delivree_at"
        ),
        {"id": vid},
    ).fetchall()

    media = db.execute(
        text("SELECT id, kind, url, thumb_url, caption FROM academy_provider_media WHERE vendor_id=:id AND is_active=1 ORDER BY sort_order, id LIMIT 24"),
        {"id": vid},
    ).fetchall()

    review_rows = db.execute(
        text(
            "SELECT r.rating, r.comment, c.client_name, r.created_at, r.reply, r.replied_at, r.booking_id, r.criteria_json "
            "FROM academy_reviews r JOIN clients c ON c.client_id=r.client_id WHERE r.vendor_id=:id AND r.status='approved' ORDER BY r.created_at DESC, r.id DESC"
        ),
        {"id": vid},
    ).fetchall()

    ranges, booked = load_availability(db, [vid], now)
    slots = compute_slots(ranges.get(vid, []), booked.get(vid, set()), now) if vid in ranges else []
    # 4 creneaux espaces : on prend le premier de chaque demi-journee a venir.
    picked, seen = [], set()
    for s in slots:
        key = (s.date(), s.hour >= 13)
        if key not in seen:
            seen.add(key)
            picked.append(s)
        if len(picked) == 4:
            break

    # --- agregats d'avis ----------------------------------------------------
    crit_totals: dict[str, list[float]] = {}
    for r in review_rows:
        if r[7]:
            try:
                for k, val in json.loads(r[7]).items():
                    if isinstance(val, (int, float)):
                        crit_totals.setdefault(k, []).append(float(val))
            except ValueError:
                pass
    criteria = [{"key": k, "value": round(sum(vs) / len(vs), 1)} for k, vs in crit_totals.items()]

    cand_like = {"avg_rating": v["avg_rating"], "mark": v["vendor_mark"], "n_reviews": v["n_reviews"], "top_override": p.top_override if p else None}
    rating = rating_of(cand_like)
    missions = max(int(v["missions"] or 0), int(v["vendor_jobs_count"] or 0))
    member = v["vendor_sign_up_at"] or v["vendor_created_at"]
    slug = (p.public_slug if p and p.public_slug else None)
    first = (v["vendor_name"] or "").split(" ")[0].lower()
    share_ref = slug or (f"{re.sub(r'[^a-z0-9]', '', first)}-{vid}" if first else str(vid))
    price_values = [int(s[2]) for s in services if s[2]]
    pick = lambda fr, en: (en if lang == "en" and en else fr)  # noqa: E731

    return {
        "vendor_id": vid,
        "slug": slug or str(vid),
        "name": (v["vendor_name"] or "").strip(),
        "short_name": display_name(v["vendor_name"]),
        "initials": initials(v["vendor_name"]),
        "image_url": v["vendor_image"],
        "cover_image_url": p.cover_image_url if p else None,
        "job": pick(certs[0][0], certs[0][1]) if certs else None,
        "city": v["vendor_address_city"],
        "districts": _districts(db, v["vendor_working_district"]),
        "member_since": member.year if member else None,
        "years_experience": p.years_experience if p else None,
        "languages": parse_languages(v["vendor_local_languages"]),
        "headline": p.headline if p else None,
        "about": (pick(p.about, p.about_en) if p and (p.about or p.about_en) else v["vendor_bio"]),
        "badges": {
            "identity": True,
            "address": bool(p and p.is_address_verified),
            "certified": [pick(c[0], c[1]) for c in {c[0]: c for c in certs}.values()],
            "insured": bool(p and p.is_insured),
            "top": is_top({"top_override": p.top_override if p else None}, rating, missions),
            "top_year": now.year,
        },
        "stats": {
            "rating": round(rating, 1) if rating else None,
            "reviews_count": int(v["n_reviews"] or 0),
            "missions": missions,
            "response_minutes": p.response_time_minutes if p else None,
            "on_time_rate": float(p.on_time_rate) if p and p.on_time_rate is not None else None,
        },
        "services": [{"id": s[3], "title": s[0], "subtitle": (" ".join((s[1] or "").split())[:70] if len((s[1] or "").strip()) > 2 else None), "price": int(s[2]) if s[2] else None} for s in services],
        "services_note": (pick(p.services_note, p.services_note_en) if p else None),
        "media": [{"id": m[0], "kind": m[1], "url": m[2], "thumb_url": m[3], "caption": m[4]} for m in media],
        "trainings": [{"title": f"{pick(c[0], c[1])} — {pick(c[3], c[4])}", "level": c[2], "delivered_at": c[5].date().isoformat() if c[5] else None} for c in certs],
        "reviews": {
            "average": round(float(v["avg_rating"]), 1) if v["avg_rating"] is not None else None,
            "count": int(v["n_reviews"] or 0),
            "criteria": criteria,
            "items": [
                {
                    "rating": int(r[0]),
                    "comment": r[1],
                    "author": (r[2] or "").split(" ", 1)[0],
                    "created_at": r[3].isoformat() if r[3] else None,
                    "reply": r[4],
                    "verified": r[6] is not None,
                }
                for r in review_rows[:reviews_limit]
            ],
        },
        "booking": {
            "visit_fee": p.visit_fee if p and p.visit_fee else (min(price_values) if price_values else None),
            "availability_known": vid in ranges,
            "slots": [{"label": slot_label(s, now, lang), "iso": s.isoformat()} for s in picked],
        },
        "share": {"url": f"{settings.public_site_url.rstrip('/')}/profil/{share_ref}", "ref": share_ref},
        "zone": {
            "lat": float(v["vendor_latitude"]) if v["vendor_latitude"] else None,
            "lng": float(v["vendor_longitude"]) if v["vendor_longitude"] else None,
            "radius_km": p.service_radius_km if p else None,
            "label": (p.zone_label if p and p.zone_label else None),
        },
    }


# ---------------------------------------------------------------------------
# Page "Reserver" : services detailles d'un prestataire
# ---------------------------------------------------------------------------
def _listify(raw) -> list[str]:
    """Texte libre ou JSON (liste de chaines ou d'objets) -> liste de libelles propres."""
    if raw is None:
        return []
    raw = str(raw).strip()
    if not raw or raw in {"-", "[]", "{}", "null"}:
        return []
    items: list = []
    try:
        parsed = json.loads(raw) if not raw.startswith(("a:", "s:", "N;")) else php_serialize.loads(raw)
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = list(parsed.values())
        else:
            items = [parsed]
    except ValueError:
        items = re.split(r"[\n;•|]|,(?![^()]*\))", raw)
    out: list[str] = []
    for it in items:
        if isinstance(it, dict):
            it = it.get("name") or it.get("title") or it.get("label") or next((v for v in it.values() if isinstance(v, str)), "")
        text_ = " ".join(str(it).split()).strip(" -•")
        if len(text_) > 1 and text_ not in out:
            out.append(text_[:120])
    return out[:12]


def build_services(db: Session, ref: str, lang: str = "fr", country: str = "TG") -> dict | None:
    """Services detailles + informations de reservation. None si le prestataire
    n'existe pas ou n'est pas eligible (meme regle que le profil public)."""
    lang = "en" if lang == "en" else "fr"
    vid = resolve_vendor_id(db, ref)
    if vid is None:
        return None
    offer, offer_params = public_provider_clause(db, country, "v")
    s_clause, s_params = service_country_clause(db, country, "s")
    ok = db.execute(
        text(
            "SELECT 1 FROM vendors v LEFT JOIN academy_trust_scores t ON t.vendor_id=v.vendor_id WHERE v.vendor_id=:id "
            f"AND v.vendor_academy_verified=1 AND ((v.vendor_academy_status='certified_provider' AND t.score_pct>=:thr) OR v.vendor_academy_status='provider') AND {offer}"
        ),
        {"id": vid, "thr": TRUST_SCORE_THRESHOLD, **offer_params},
    ).first()
    if not ok:
        return None

    rows = db.execute(
        text(
            "SELECT s.s_id, s.s_title, s.s_desp, s.s_min_price, s.s_exp, s.s_sub_services, s.s_tools_used, s.s_options, "
            "sc.subcat_name_fr, sc.subcat_name_en FROM services s LEFT JOIN sub_categories sc ON sc.subcat_id=s.s_subcat_id "
            f"WHERE s.s_vendor_id=:id AND s.s_is_active='1' AND {s_clause} ORDER BY (s.s_min_price IS NULL OR s.s_min_price=0), s.s_min_price, s.s_id LIMIT 40"
        ),
        {"id": vid, **s_params},
    ).fetchall()
    p = db.query(ProviderProfile).filter(ProviderProfile.vendor_id == vid).first()
    pick = lambda fr, en: (en if lang == "en" and en else fr)  # noqa: E731

    services = []
    for r in rows:
        desc = " ".join((r[2] or "").split())
        services.append(
            {
                "id": r[0],
                "title": r[1],
                "description": desc if len(desc) > 2 else None,
                "price": int(r[3]) if r[3] else None,
                "experience": (str(r[4]).strip() if r[4] and len(str(r[4]).strip()) > 0 and str(r[4]).strip() != "-" else None),
                "includes": _listify(r[5]),
                "tools": _listify(r[6]),
                "options": _listify(r[7]),
                "category": pick(r[8], r[9]),
            }
        )
    prices = [s["price"] for s in services if s["price"]]
    return {
        "vendor_id": vid,
        "services": services,
        "visit_fee": p.visit_fee if p and p.visit_fee else None,
        "note": pick(p.services_note, p.services_note_en) if p else None,
        "min_price": min(prices) if prices else None,
    }
