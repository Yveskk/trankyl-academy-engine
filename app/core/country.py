"""Pays et langue de la requete.

Chaque endpoint (public ou admin) travaille dans UN pays et UNE langue :
  - pays   : parametre `?country=TG` ou en-tete `X-Country: TG` (le parametre l'emporte) ;
  - langue : parametre `?lang=fr|en` ou en-tete `X-Lang` ; sinon `Accept-Language` ; sinon fr.
Le client web envoie ces deux en-tetes sur TOUTES ses requetes : aucun endpoint ne les oublie."""
from __future__ import annotations

import json
import re
import threading
import time

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.countries import LEGACY_MARKETPLACE_IDS, active_countries, reference_country

FALLBACK_COUNTRY = "TG"
_CODE = re.compile(r"^[A-Za-z]{2}$")


def normalize(value: str | None) -> str | None:
    v = (value or "").strip()
    return v.upper() if _CODE.match(v) else None


def requested_country(request: Request) -> str | None:
    return normalize(request.query_params.get("country") or request.headers.get("x-country"))


_topbar_cache: tuple[float, list[str]] | None = None
_topbar_lock = threading.Lock()


def _topbar_codes(db: Session) -> list[str]:
    """Pays proposes par la bande verte du site (section `topbar`), a defaut de pays geres dans l'admin (table
    `academy_countries` vide) : le selecteur de l'admin et celui du site montrent ainsi LA MEME liste."""
    global _topbar_cache
    now = time.monotonic()
    with _topbar_lock:
        if _topbar_cache and _topbar_cache[0] > now:
            return _topbar_cache[1]
    codes: list[str] = []
    try:
        raw = db.execute(text("SELECT payload_json FROM academy_content_sections WHERE `key`='topbar' ORDER BY (country_code=:c) DESC, updated_at DESC LIMIT 1"), {"c": FALLBACK_COUNTRY}).scalar()
        for c in (json.loads(raw) if raw else {}).get("countries", []):
            code = normalize(c.get("code"))
            if code and code not in codes:
                codes.append(code)
    except Exception:  # noqa: BLE001  (table absente / JSON invalide : liste par defaut)
        db.rollback()
    if not codes:
        from app.services.home_defaults import SECTIONS

        codes = [c["code"] for c in SECTIONS["topbar"]["payload"]["countries"]]
    with _topbar_lock:
        _topbar_cache = (now + 30, codes)
    return codes


def known_codes(db: Session) -> list[str]:
    rows = active_countries(db)
    return [c["code"] for c in rows] if rows else _topbar_codes(db)


def default_country(db: Session) -> str:
    return reference_country(db)


def public_country(request: Request, db: Session) -> str:
    """Pays d'une requete publique : celui demande s'il est connu, sinon le pays par defaut (jamais d'erreur)."""
    code = requested_country(request)
    if code and code in known_codes(db):
        return code
    return default_country(db)


def request_lang(request: Request) -> str:
    raw = request.query_params.get("lang") or request.headers.get("x-lang") or request.headers.get("accept-language", "")
    return "en" if raw.strip().lower().startswith("en") else "fr"
