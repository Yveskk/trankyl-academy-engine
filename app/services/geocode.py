"""Geocodage inverse (coordonnees -> adresse) et lecture d'un lien Google Maps, pour pre-remplir le profil prestataire.

Meme principe que l'application prestataire et l'ancien site : le prestataire donne sa position (GPS, carte ou lien
Google Maps) et le pays, la ville, la rue et le code postal sont deduits des coordonnees — il ne les tape pas.

- Service : OpenStreetMap Nominatim (sans cle). Une cle Google (`GEOCODING_API_KEY`) est utilisee en priorite si elle existe.
- Les liens ne sont suivis que pour des domaines Google Maps (aucune requete vers une adresse quelconque)."""
from __future__ import annotations

import os
import re
import threading
import time
from urllib.parse import urlparse

import httpx

_UA = "TrankylAcademy/1.0 (contact: admin@trankyl.com)"
_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_lock = threading.Lock()
_ALLOWED = re.compile(r"(^|\.)(google\.[a-z.]{2,6}|goo\.gl|g\.co|g\.page)$", re.I)
_COORD_PATTERNS = [
    r"@(-?\d+\.\d+),(-?\d+\.\d+)",
    r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
    r"[?&](?:q|ll|query|destination)=(-?\d+\.\d+)(?:,|%2C)(-?\d+\.\d+)",
    r"/maps/place/[^/]+/(-?\d+\.\d+),(-?\d+\.\d+)",
]


class GeocodeError(Exception):
    pass


def _valid(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180


def coords_from_url(url: str) -> tuple[float, float]:
    """Lit les coordonnees d'un lien Google Maps (les liens courts sont suivis, uniquement vers Google)."""
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme not in ("http", "https") or not _ALLOWED.search(host):
        raise GeocodeError("Collez un lien Google Maps (maps.app.goo.gl ou google.com/maps).")
    final = url
    if re.search(r"goo\.gl|g\.co|g\.page", host):
        try:
            with httpx.Client(follow_redirects=True, timeout=8, headers={"User-Agent": _UA}, max_redirects=5) as c:
                final = str(c.get(url).url)
        except httpx.HTTPError:
            raise GeocodeError("Impossible de lire ce lien. Vérifiez-le ou utilisez votre position.")
        if not _ALLOWED.search((urlparse(final).hostname or "").lower()):
            raise GeocodeError("Ce lien ne mène pas à Google Maps.")
    for pat in _COORD_PATTERNS:
        m = re.search(pat, final)
        if m and _valid(float(m[1]), float(m[2])):
            return float(m[1]), float(m[2])
    raise GeocodeError("Aucune position trouvée dans ce lien.")


def _nominatim(lat: float, lng: float, zoom: int) -> dict:
    r = httpx.get("https://nominatim.openstreetmap.org/reverse", params={"format": "jsonv2", "addressdetails": 1, "accept-language": "fr", "lat": lat, "lon": lng, "zoom": zoom},
                  headers={"User-Agent": _UA}, timeout=10)
    r.raise_for_status()
    return r.json().get("address") or {}


def _city_of(a: dict) -> str:
    return a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county") or a.get("state_district") or ""


def _from_nominatim(lat: float, lng: float) -> dict:
    try:
        a = _nominatim(lat, lng, 18)
        city = _city_of(a)
        if not city:  # quartier sans commune dans la reponse : essai a l'echelle de la commune (jamais la region, qui n'est pas une ville)
            city = _city_of(_nominatim(lat, lng, 12))
    except (httpx.HTTPError, ValueError):
        raise GeocodeError("Le service de localisation ne répond pas. Saisissez votre adresse.")
    street = a.get("road") or a.get("pedestrian") or a.get("footway") or ""
    area = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or a.get("city_district") or ""
    return {"country_code": (a.get("country_code") or "").upper(), "city": city, "street_number": a.get("house_number") or "", "street_name": street, "postal_code": a.get("postcode") or "", "area": area}


def _from_google(lat: float, lng: float, key: str) -> dict:
    try:
        d = httpx.get("https://maps.googleapis.com/maps/api/geocode/json", params={"latlng": f"{lat},{lng}", "key": key, "language": "fr"}, timeout=10).json()
    except (httpx.HTTPError, ValueError):
        raise GeocodeError("Le service de localisation ne répond pas. Saisissez votre adresse.")
    if d.get("status") != "OK" or not d.get("results"):
        raise GeocodeError("Adresse non trouvée pour cette position.")
    comps = d["results"][0]["address_components"]

    def get(t: str, short=False) -> str:
        c = next((x for x in comps if t in x["types"]), None)
        return (c["short_name"] if short else c["long_name"]) if c else ""

    return {"country_code": get("country", True).upper(), "city": get("locality") or get("administrative_area_level_2"), "street_number": get("street_number"), "street_name": get("route"),
            "postal_code": get("postal_code"), "area": get("sublocality") or get("neighborhood")}


def reverse(lat: float, lng: float) -> dict:
    if not _valid(lat, lng):
        raise GeocodeError("Position invalide.")
    k = (round(lat, 4), round(lng, 4))
    with _lock:
        hit = _cache.get(k)
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
    key = os.environ.get("GEOCODING_API_KEY")
    out = _from_google(lat, lng, key) if key else _from_nominatim(lat, lng)
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[k] = (time.time(), out)
    return out
