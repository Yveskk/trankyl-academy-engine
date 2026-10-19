"""Recherche de prestataires (page /recherche).

Un texte libre ("mon robinet de cuisine fuit depuis hier") est interprete par
regles (sous-categorie du catalogue, urgence, mots-cles) — sans appel IA, donc
instantane et previsible — puis les prestataires ELIGIBLES (certifies, verifies,
score de confiance >= seuil : meme regle que le matching existant) sont
filtres, classes et pagines.

Performance : UNE requete SQL pour les candidats (sous-requetes correlees
indexees), +2 requetes en lot (disponibilites, reservations a venir) ; filtres
fins, classement et pagination se font en memoire sur quelques dizaines de
lignes.

Les prestataires sans donnees de disponibilite restent visibles : l'absence
de donnee n'est jamais une exclusion."""
import json
import math
import re
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta, time as dtime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import ContentSection
from app.services.countries import marketplace_country_id, provider_offer_clause, public_provider_clause, service_country_clause
from app.services.trust_score import TRUST_SCORE_THRESHOLD

# ---------------------------------------------------------------------------
# Temps local
# ---------------------------------------------------------------------------
def local_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=settings.local_utc_offset_hours)


# ---------------------------------------------------------------------------
# Interpretation du texte libre
# ---------------------------------------------------------------------------
def normalize(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# Chaque groupe : `targets` = sous-chaines recherchees dans le NOM normalise
# d'une sous-categorie du catalogue ; `triggers` = debuts de mots, dans la
# requete, qui activent le groupe. Modifiable sans deploiement via la section
# `search_synonyms` (academy_content_sections, payload_json {"groups": [...]}).
DEFAULT_SYNONYM_GROUPS: list[dict] = [
    {"targets": ["plomb", "plumb"], "triggers": ["plomb", "robinet", "fuite", "tuyau", "evier", "wc", "toilet", "canalis", "sanitaire", "lavabo", "douche", "chasse", "leak", "pipe", "tap", "faucet", "drain"]},
    {"targets": ["electr"], "triggers": ["electr", "courant", "prise", "disjonct", "ampoule", "cable", "lumiere", "compteur", "court circuit", "wiring", "socket", "light"]},
    {"targets": ["nettoy", "menage", "clean"], "triggers": ["menage", "nettoy", "poussiere", "laver", "lavage", "vitre", "clean", "dust"]},
    {"targets": ["garde", "nounou", "child", "babysit"], "triggers": ["nounou", "enfant", "bebe", "garde", "babysit", "baby", "nanny", "child"]},
    {"targets": ["cuisin", "traiteur", "cater"], "triggers": ["repas", "traiteur", "cuisin", "buffet", "plat", "cook", "meal", "cater"]},
    {"targets": ["clim", "air cond"], "triggers": ["clim", "froid", "split", "refrigerat", "air cond", "cooling"]},
    {"targets": ["menuis", "carpent", "wood"], "triggers": ["menuis", "meuble", "porte", "fenetre", "bois", "armoire", "carpent", "furniture", "door", "window"]},
    {"targets": ["peint", "paint"], "triggers": ["peintur", "peindre", "repeindre", "mur", "paint", "wall"]},
    {"targets": ["coiff", "beaut", "hair"], "triggers": ["coiff", "tresse", "beaute", "maquill", "manucure", "ongle", "hair", "braid", "makeup", "nail"]},
    {"targets": ["chauffeur", "driver", "transport"], "triggers": ["chauffeur", "trajet", "transport", "taxi", "conduire", "livraison", "driver", "ride"]},
    {"targets": ["coutur", "tailor", "sew"], "triggers": ["coutur", "retouche", "robe", "tailleur", "ourlet", "pagne", "sew", "tailor", "dress"]},
    {"targets": ["domicile", "home help", "elder"], "triggers": ["personne agee", "domicile", "senior", "malade", "vieux", "elderly", "carer"]},
]

URGENCY_RULES: list[tuple[str, list[str]]] = [
    ("today", ["aujourd", "urgent", "maintenant", "tout de suite", "vite", "ce soir", "ce matin", "hier", "today", "now", "asap", "tonight", "yesterday"]),
    ("tomorrow", ["demain", "tomorrow"]),
    ("weekend", ["week end", "weekend", "samedi", "dimanche", "saturday", "sunday"]),
]

_synonyms_cache: tuple[float, list[dict]] | None = None
_synonyms_lock = threading.Lock()


def load_synonym_groups(db: Session) -> list[dict]:
    """Groupes par defaut, ou ceux saisis par l'admin (cache 60 s)."""
    global _synonyms_cache
    now = time.monotonic()
    with _synonyms_lock:
        if _synonyms_cache and _synonyms_cache[0] > now:
            return _synonyms_cache[1]
    groups = DEFAULT_SYNONYM_GROUPS
    # Vocabulaire commun a tous les pays : conserve dans le pays de reference.
    row = db.query(ContentSection).filter(ContentSection.key == "search_synonyms", ContentSection.country_code == "TG", ContentSection.is_active.is_(True)).first()
    if row and row.payload_json:
        try:
            custom = json.loads(row.payload_json).get("groups")
            if isinstance(custom, list) and custom:
                groups = [g for g in custom if isinstance(g, dict) and g.get("targets") and g.get("triggers")]
        except ValueError:
            pass
    with _synonyms_lock:
        _synonyms_cache = (now + 60, groups)
    return groups


def interpret_query(db: Session, q: str, lang: str = "fr") -> dict:
    """-> {subcategory_ids, label, keywords, urgency}"""
    qn = normalize(q)
    tokens = qn.split()
    result = {"subcategory_ids": [], "label": None, "keywords": [], "urgency": None}
    if not tokens:
        return result

    for urgency, triggers in URGENCY_RULES:
        if any(t in qn for t in triggers):
            result["urgency"] = urgency
            break

    def hit(trigger: str) -> str | None:
        """Mot de la requete qui active `trigger` (debut de mot, ou expression)."""
        if " " in trigger:
            return trigger if trigger in qn else None
        for tok in tokens:
            if tok == trigger or (len(trigger) >= 4 and tok.startswith(trigger)) or (len(tok) >= 4 and trigger.startswith(tok)):
                return tok  # "fuit" active le declencheur "fuite" et inversement
        return None

    # Groupes de synonymes actives par la requete : (cibles, mots de la requete qui l'ont active)
    activated: list[tuple[list[str], list[str]]] = []
    for g in load_synonym_groups(db):
        matched = list(dict.fromkeys(m for m in (hit(t) for t in g["triggers"]) if m))
        if matched:
            activated.append((g["targets"], matched))

    rows = db.execute(
        text("SELECT subcat_id, subcat_name_fr, subcat_name_en FROM sub_categories WHERE subcat_is_active=1")
    ).fetchall()
    scored: list[tuple[int, int, str, str | None, list[str]]] = []
    for sid, fr, en in rows:
        name_n = normalize(fr) + " " + normalize(en)
        score, kws = 0, []
        # Un groupe pese 4 points PAR mot de la requete qui l'active : "robinet ... fuit"
        # (2 mots du groupe plomberie) l'emporte sur un seul "cuisine" (1 mot du groupe cuisine).
        for targets, matched in activated:
            if any(t in name_n for t in targets):
                score += 4 * len(matched)
                kws += matched
        for tok in tokens:
            if tok in kws:  # deja compte par un groupe de synonymes
                continue
            if len(tok) >= 4 and any(w.startswith(tok[:5]) or tok.startswith(w[:5]) for w in name_n.split() if len(w) >= 4):
                score += 1
                kws.append(tok)
        if score:
            scored.append((score, sid, fr, en, list(dict.fromkeys(kws))))
    scored.sort(key=lambda r: (-r[0], r[1]))
    if scored:
        best = scored[0][0]
        top = [r for r in scored if r[0] == best]
        result["subcategory_ids"] = [r[1] for r in top]
        first = top[0]
        result["label"] = first[3] if lang == "en" and first[3] else first[2]
        result["keywords"] = first[4][:4]
    return result


# ---------------------------------------------------------------------------
# Disponibilites (creneaux hebdomadaires)
# ---------------------------------------------------------------------------
def _to_time(v) -> dtime:
    if isinstance(v, dtime):
        return v
    if isinstance(v, timedelta):  # pymysql renvoie TIME sous forme de timedelta
        secs = int(v.total_seconds())
        return dtime(secs // 3600 % 24, secs % 3600 // 60)
    return datetime.strptime(str(v), "%H:%M:%S").time()


def compute_slots(ranges: list[tuple[int, object, object]], booked: set[tuple[date, int]], now: datetime, days: int = 7, step_minutes: int = 60) -> list[datetime]:
    """Prochains creneaux libres. `ranges` : (weekday, debut, fin) ; `booked` :
    (date, heure) deja pris. Un creneau doit commencer au moins 30 min apres `now`."""
    out: list[datetime] = []
    for offset in range(days):
        d = now.date() + timedelta(days=offset)
        for weekday, start, end in ranges:
            if weekday != d.weekday():
                continue
            cur = datetime.combine(d, _to_time(start))
            stop = datetime.combine(d, _to_time(end))
            while cur + timedelta(minutes=step_minutes) <= stop:
                if cur > now + timedelta(minutes=30) and (d, cur.hour) not in booked:
                    out.append(cur)
                cur += timedelta(minutes=step_minutes)
    return sorted(set(out))


def load_availability(db: Session, vendor_ids: list[int], now: datetime) -> tuple[dict[int, list], dict[int, set]]:
    """2 requetes pour tout le lot : plages hebdomadaires et reservations des 7 prochains jours."""
    if not vendor_ids:
        return {}, {}
    ranges: dict[int, list] = {}
    for vid, wd, st, en in db.execute(
        text("SELECT vendor_id, weekday, start_time, end_time FROM academy_provider_availability WHERE is_active=1 AND vendor_id IN :ids").bindparams(bindparam("ids", expanding=True)),
        {"ids": vendor_ids},
    ):
        ranges.setdefault(vid, []).append((wd, st, en))
    booked: dict[int, set] = {}
    for vid, d, t in db.execute(
        text(
            "SELECT bk_vendor_id, bk_date, bk_time FROM bookings WHERE bk_vendor_id IN :ids AND bk_date BETWEEN :d0 AND :d1 "
            "AND (bk_service_status IS NULL OR bk_service_status NOT IN ('3','4'))"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": vendor_ids, "d0": now.date(), "d1": now.date() + timedelta(days=7)},
    ):
        m = re.match(r"\s*(\d{1,2})", str(t or ""))
        if d and m:
            booked.setdefault(vid, set()).add((d, int(m.group(1))))
    return ranges, booked


# ---------------------------------------------------------------------------
# Requete candidats
# ---------------------------------------------------------------------------
_NOT_CANCELLED = "(b.bk_service_status IS NULL OR b.bk_service_status NOT IN ('3','4'))"


def _first_metier(col: str) -> str:
    return (
        f"(SELECT m.{col} FROM academy_certifications c JOIN academy_niveaux n ON n.id=c.niveau_id "
        "JOIN academy_metiers m ON m.id=n.metier_id WHERE c.vendor_id=v.vendor_id ORDER BY c.delivree_at LIMIT 1)"
    )


def fetch_candidates(db: Session, subcat_ids: list[int], country: str, city: str | None, only_insured: bool) -> list[dict]:
    s_clause, s_params = service_country_clause(db, country, "s")  # seuls les services publies dans CE pays comptent
    price_filter = " AND s.s_subcat_id IN :sub_s" if subcat_ids else ""
    sql = (
        "SELECT v.vendor_id, v.vendor_name, v.vendor_image, v.vendor_address_city, v.vendor_working_district, v.vendor_latitude, v.vendor_longitude, "
        "v.vendor_mark, v.vendor_jobs_count, v.vendor_local_languages, v.vendor_sign_up_at, v.vendor_created_at, COALESCE(t.score_pct,0) AS score_pct, "
        "(SELECT AVG(r.rating) FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved') AS avg_rating, "
        "(SELECT COUNT(*) FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved') AS n_reviews, "
        f"(SELECT COUNT(*) FROM bookings b WHERE b.bk_vendor_id=v.vendor_id AND {_NOT_CANCELLED}) AS missions, "
        "p.is_insured, p.top_override, p.is_featured, p.featured_order, p.response_time_minutes, p.public_slug, p.on_time_rate, p.years_experience, "
        f"(SELECT MIN(s.s_min_price) FROM services s WHERE s.s_vendor_id=v.vendor_id AND s.s_is_active='1' AND s.s_min_price>0 AND {s_clause}{price_filter}) AS price, "
        + _first_metier("nom") + " AS metier, " + _first_metier("nom_en") + " AS metier_en, "
        "(SELECT r.comment FROM academy_reviews r WHERE r.vendor_id=v.vendor_id AND r.status='approved' AND r.comment IS NOT NULL AND r.comment<>'' ORDER BY r.created_at DESC LIMIT 1) AS quote "
        "FROM vendors v LEFT JOIN academy_trust_scores t ON t.vendor_id=v.vendor_id LEFT JOIN academy_provider_profiles p ON p.vendor_id=v.vendor_id "
        "WHERE v.vendor_academy_verified=1 AND ((v.vendor_academy_status='certified_provider' AND t.score_pct>=:thr) OR v.vendor_academy_status='provider')"
    )
    params: dict = {"thr": TRUST_SCORE_THRESHOLD, **s_params}
    binds = []
    offer, offer_params = public_provider_clause(db, country, "v")  # visible dans ce pays = y publie un service
    sql += f" AND {offer}"
    params.update(offer_params)
    if city:
        sql += " AND v.vendor_address_city LIKE :city"
        params["city"] = f"%{city}%"
    if only_insured:
        sql += " AND p.is_insured=1"
    if subcat_ids:
        sql += (
            f" AND (EXISTS (SELECT 1 FROM services s WHERE s.s_vendor_id=v.vendor_id AND s.s_is_active='1' AND {s_clause} AND s.s_subcat_id IN :sub_s)"
            " OR EXISTS (SELECT 1 FROM academy_certifications c JOIN academy_niveaux n ON n.id=c.niveau_id WHERE c.vendor_id=v.vendor_id AND n.metier_id IN :sub_i))"
        )
        params["sub_s"] = [str(i) for i in subcat_ids]
        params["sub_i"] = subcat_ids
        binds += [bindparam("sub_s", expanding=True), bindparam("sub_i", expanding=True)]
    stmt = text(sql)
    if binds:
        stmt = stmt.bindparams(*binds)

    cols = [
        "vendor_id", "name", "image", "city", "districts", "lat", "lng", "mark", "jobs", "languages", "signup", "created", "trust",
        "avg_rating", "n_reviews", "missions", "insured", "top_override", "featured", "featured_order", "response_minutes", "slug", "on_time", "years",
        "price", "metier", "metier_en", "quote",
    ]
    return [dict(zip(cols, row)) for row in db.execute(stmt, params).fetchall()]


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------
def display_name(name: str | None) -> str:
    parts = (name or "").strip().split()
    if len(parts) < 2:
        return parts[0] if parts else ""
    return f"{parts[0]} {parts[1][0].upper()}."


def initials(name: str | None) -> str:
    return "".join(p[0].upper() for p in (name or "").split()[:2]) or "?"


def parse_languages(raw: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,;/|]", raw or "") if p.strip()]


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rating_of(c: dict, min_reviews: int = 3) -> float | None:
    avg = float(c["avg_rating"]) if c["avg_rating"] is not None else None
    mark = float(c["mark"]) if c["mark"] else None
    n = int(c["n_reviews"] or 0)
    return avg if (avg is not None and n >= min_reviews) else (mark or avg)


def is_top(c: dict, rating: float | None, missions: int) -> bool:
    if c["top_override"] is not None:
        return bool(c["top_override"])
    return bool(rating and rating >= 4.8 and missions >= 50)


def slot_label(dt: datetime, now: datetime, lang: str) -> str:
    days_fr = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
    days_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    delta = (dt.date() - now.date()).days
    if lang == "en":
        day = "Today" if delta == 0 else "Tomorrow" if delta == 1 else days_en[dt.weekday()]
    else:
        day = "Auj." if delta == 0 else "Dem." if delta == 1 else days_fr[dt.weekday()]
    return f"{day}|{dt.hour}h" if dt.minute == 0 else f"{day}|{dt.hour}h{dt.minute:02d}"


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------
SORTS = {"recommended", "rating", "price", "distance", "missions"}


def search_providers(
    db: Session,
    *,
    q: str = "",
    subcategory_id: int | None = None,
    country: str = "TG",
    city: str | None = None,
    district: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    availability: str | None = None,
    min_rating: float = 0,
    identity: bool = False,
    certified: bool = False,
    insured: bool = False,
    top: bool = False,
    languages: list[str] | None = None,
    sort: str = "recommended",
    limit: int = 20,
    offset: int = 0,
    lang: str = "fr",
) -> dict:
    lang = "en" if lang == "en" else "fr"
    now = local_now()
    interp = interpret_query(db, q, lang) if q.strip() else {"subcategory_ids": [], "label": None, "keywords": [], "urgency": None}
    sub_ids = [subcategory_id] if subcategory_id else interp["subcategory_ids"]
    if subcategory_id and not interp["label"]:
        row = db.execute(text("SELECT subcat_name_fr, subcat_name_en FROM sub_categories WHERE subcat_id=:i"), {"i": subcategory_id}).first()
        if row:
            interp["label"] = row[1] if lang == "en" and row[1] else row[0]

    cands = fetch_candidates(db, sub_ids, country, city, insured)
    ranges, booked = load_availability(db, [c["vendor_id"] for c in cands], now)

    # Origine pour les distances : position GPS, sinon barycentre des prestataires du quartier.
    origin = (lat, lng) if lat is not None and lng is not None else None
    if origin is None and district:
        dn = normalize(district)
        pts = [(float(c["lat"]), float(c["lng"])) for c in cands if c["lat"] and c["lng"] and dn in normalize(c["districts"])]
        if pts:
            origin = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    items: list[dict] = []
    for c in cands:
        vid = c["vendor_id"]
        rating = rating_of(c)
        missions = max(int(c["missions"] or 0), int(c["jobs"] or 0))
        top_flag = is_top(c, rating, missions)
        has_cert = c["metier"] is not None
        langs = parse_languages(c["languages"])

        if min_rating and not (rating and rating >= min_rating):
            continue
        if certified and not has_cert:
            continue
        if top and not top_flag:
            continue
        # "Identite verifiee" : tous les candidats le sont deja (filtre d'eligibilite) ;
        # le parametre est conserve pour que l'interface reste coherente.
        if languages:
            ln = {normalize(x) for x in langs}
            if not any(normalize(x) in ln for x in languages):
                continue

        slots = compute_slots(ranges.get(vid, []), booked.get(vid, set()), now) if vid in ranges else []
        known = vid in ranges
        avail = {"today": False, "tomorrow": False, "weekend": False}
        for s in slots:
            d = (s.date() - now.date()).days
            avail["today"] |= d == 0
            avail["tomorrow"] |= d == 1
            avail["weekend"] |= s.weekday() >= 5
        if availability in avail and known and not avail[availability]:
            continue

        dist = None
        if origin and c["lat"] and c["lng"]:
            dist = round(haversine_km(origin[0], origin[1], c["lat"], c["lng"]), 1)

        score = (
            (100 if c["featured"] else 0)
            + (rating or 0) * 10
            + math.log1p(int(c["n_reviews"] or 0)) * 3
            + math.log1p(missions) * 2
            + float(c["trust"]) / 10
            + (4 if top_flag else 0)
            + (5 if avail["today"] else 0)
            - (dist * 0.8 if dist is not None else 0)
        )
        items.append(
            {
                "vendor_id": vid,
                "name": display_name(c["name"]),
                "initials": initials(c["name"]),
                "image_url": c["image"],
                "job": (interp["label"] if sub_ids and interp["label"] else (c["metier_en"] if lang == "en" and c["metier_en"] else c["metier"])),
                "city": c["city"],
                "rating": round(rating, 1) if rating else None,
                "reviews_count": int(c["n_reviews"] or 0),
                "missions": missions,
                "distance_km": dist,
                "response_minutes": c["response_minutes"],
                "price_from": int(c["price"]) if c["price"] else None,
                "quote": c["quote"],
                "languages": langs,
                "badges": {"verified": True, "certified": has_cert, "insured": bool(c["insured"]), "top": top_flag},
                "availability_known": known,
                "next_slot": slot_label(slots[0], now, lang) if slots else None,
                "next_slot_iso": slots[0].isoformat() if slots else None,
                "available_today": avail["today"],
                "lat": float(c["lat"]) if c["lat"] else None,
                "lng": float(c["lng"]) if c["lng"] else None,
                "profile_url": f"/profil/{c['slug'] or vid}",
                "_score": score,
                "_price": int(c["price"]) if c["price"] else 10**9,
            }
        )

    if sort == "rating":
        items.sort(key=lambda i: (-(i["rating"] or 0), -i["reviews_count"], -i["_score"]))
    elif sort == "price":
        items.sort(key=lambda i: (i["_price"], -i["_score"]))
    elif sort == "distance":
        items.sort(key=lambda i: (i["distance_km"] is None, i["distance_km"] or 0, -i["_score"]))
    elif sort == "missions":
        items.sort(key=lambda i: (-i["missions"], -i["_score"]))
    else:
        items.sort(key=lambda i: -i["_score"])

    total = len(items)
    prices = sorted(i["price_from"] for i in items if i["price_from"])
    budget = None
    if prices:
        low = prices[0]
        high = prices[min(len(prices) - 1, max(0, int(len(prices) * 0.75)))]
        high = max(high, int(low * 1.6)) if high == low else high
        budget = {"low": int(round(low / 500) * 500), "high": int(round(high / 500) * 500)}

    page = items[offset : offset + limit]
    for i in page:
        i.pop("_score", None)
        i.pop("_price", None)

    return {
        "total": total,
        "items": page,
        "interpretation": {
            "label": interp["label"],
            "keywords": interp["keywords"],
            "urgency": interp["urgency"],
            "budget": budget,
            "subcategory_ids": sub_ids,
            "city": city,
            "district": district,
        },
    }


def list_locations(db: Session, country: str) -> list[dict]:
    """Villes actives et leurs quartiers (tables `cities` / `district` du marketplace)."""
    cid = marketplace_country_id(db, country)
    rows = db.execute(
        text(
            "SELECT c.city_id, c.city_name, d.district_name FROM cities c LEFT JOIN district d ON d.district_city_id=c.city_id AND d.district_is_active=1 "
            "WHERE c.city_is_active=1 AND (:cid IS NULL OR c.city_country_id=:cid) ORDER BY c.city_name, d.district_name"
        ),
        {"cid": cid},
    ).fetchall()
    out: dict[int, dict] = {}
    for city_id, city_name, district in rows:
        entry = out.setdefault(city_id, {"city": city_name, "districts": []})
        if district:
            entry["districts"].append(district)
    return list(out.values())
