"""Reservation d'un prestataire : options, calcul du prix, creation de la reservation.

Meme modele que le site Trankyl (trankyl_website) et que `bookService` du backend Node :
  - un service, une unite/un prix, une quantite, des options payantes ;
  - date + heure, adresse du client, quartier, position (lien Google Maps ou point sur la carte) ;
  - frais de MISE EN RELATION (grille selon la note du prestataire, 1000 par defaut) ;
  - code promo (pourcentage ou montant fixe) ;
  - paiement : especes, ou en ligne via SEMOA (memes identifiants que le backend Trankyl ; voir app/services/semoa.py).

Securite : le client n'envoie JAMAIS un prix. Tout est recalcule ici a partir de la base (prix du service,
options, frais, coupon). La reservation est ecrite dans la table partagee `bookings`."""
from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import booking_payment as bp
from app.services import php_serialize
from app.services import semoa
from app.services.countries import provider_offer_clause, public_provider_clause, service_country_clause, vendor_country_clause
from app.services.provider_profile import resolve_vendor_id
from app.services.search import compute_slots, load_availability, local_now, slot_label
from app.services.trust_score import TRUST_SCORE_THRESHOLD

LINKING_DEFAULT = 1000  # meme valeur que le backend Node quand aucune grille ne correspond
_MAPS = re.compile(r"^https://(www\.)?(google\.[a-z.]{2,6}/maps|maps\.google\.[a-z.]{2,6}|maps\.app\.goo\.gl|goo\.gl/maps)", re.I)
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def online_available() -> bool:
    """Le paiement en ligne est propose si SEMOA est configure ici, ou si la reservation est deleguee au backend Trankyl."""
    return semoa.configured() or bool(settings.node_api_url)


class BookingError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


# --------------------------------------------------------------------------- lecture
def listed_vendor(db: Session, ref: str, country: str) -> dict | None:
    """Prestataire public DANS CE PAYS (meme regle que le profil / la recherche) ou None."""
    vid = resolve_vendor_id(db, ref)
    if vid is None:
        return None
    offer, offer_params = public_provider_clause(db, country, "v")
    row = db.execute(
        text(
            "SELECT v.vendor_id, v.vendor_name, v.vendor_address_city, v.vendor_mark, v.vendor_currency_id, v.vendor_country_code, v.vendor_phone "
            "FROM vendors v LEFT JOIN academy_trust_scores t ON t.vendor_id=v.vendor_id WHERE v.vendor_id=:id AND v.vendor_academy_verified=1 "
            f"AND ((v.vendor_academy_status='certified_provider' AND t.score_pct>=:thr) OR v.vendor_academy_status='provider') AND {offer}"
        ),
        {"id": vid, "thr": TRUST_SCORE_THRESHOLD, **offer_params},
    ).mappings().first()
    return dict(row) if row else None


def linking_amount(db: Session, vendor_mark) -> int:
    """Frais de mise en relation : grille selon la note du prestataire, sinon 1000."""
    try:
        mark = float(vendor_mark or 0)
    except (TypeError, ValueError):
        mark = 0.0
    if mark > 0:
        row = db.execute(text("SELECT lkg_amount FROM linking_grids WHERE lkg_min <= :m AND lkg_max > :m LIMIT 1"), {"m": mark}).first()
        if row and row[0] is not None:
            return int(round(float(row[0])))
    return LINKING_DEFAULT


def _json_list(raw: str | None) -> list:
    try:
        data = json.loads(raw or "")
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def _unit_labels(db: Session, ids: list[int], lang: str) -> dict[int, str]:
    if not ids:
        return {}
    rows = db.execute(text("SELECT sv_unit_id, sv_unit_wording_fr, sv_unit_wording_en FROM service_unities WHERE sv_unit_id IN :i").bindparams(bindparam("i", expanding=True)), {"i": ids}).fetchall()
    return {r[0]: (r[2] if lang == "en" and r[2] else r[1]) for r in rows}


def service_pricing(db: Session, row, lang: str = "fr") -> dict:
    """Prix et options d'un service. `s_sub_services` JSON = unites tarifees [{unit_id, price}] ; sinon un
    forfait au prix minimum. `s_options` JSON = options payantes [{name, price}]."""
    units_raw = [u for u in _json_list(row["s_sub_services"]) if isinstance(u, dict) and str(u.get("price", "")).replace(".", "", 1).isdigit()]
    labels = _unit_labels(db, [int(u["unit_id"]) for u in units_raw if str(u.get("unit_id", "")).isdigit()], lang)
    units = [
        {"unit_id": str(u.get("unit_id") or i), "label": labels.get(int(u["unit_id"])) if str(u.get("unit_id", "")).isdigit() else None, "price": int(float(u["price"]))}
        for i, u in enumerate(units_raw)
        if float(u["price"]) > 0
    ]
    if not units and row["s_min_price"]:
        units = [{"unit_id": "0", "label": None, "price": int(row["s_min_price"])}]
    options = [
        {"name": str(o["name"])[:120], "price": int(float(o["price"]))}
        for o in php_serialize.load_list(row["s_options"])
        if isinstance(o, dict) and o.get("name") and str(o.get("price", "")).replace(".", "", 1).isdigit() and float(o["price"]) > 0
    ]
    return {"units": units, "options": options}


def _districts_of(db: Session, city_name: str | None) -> list[dict]:
    if not city_name:
        return []
    rows = db.execute(
        text(
            "SELECT d.district_id, d.district_name FROM district d JOIN cities c ON c.city_id=d.district_city_id "
            "WHERE d.district_is_active=1 AND LOWER(c.city_name)=LOWER(:c) ORDER BY d.district_name"
        ),
        {"c": city_name},
    ).fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


def booking_options(db: Session, ref: str, lang: str = "fr", country: str = "TG") -> dict | None:
    v = listed_vendor(db, ref, country)
    if v is None:
        return None
    s_clause, s_params = service_country_clause(db, country, "s")  # seuls les services publies dans ce pays
    rows = db.execute(
        text(
            "SELECT s.s_id, s.s_title, s.s_desp, s.s_min_price, s.s_sub_services, s.s_options, s.s_subcat_id FROM services s "
            f"WHERE s.s_vendor_id=:id AND s.s_is_active='1' AND {s_clause} ORDER BY (s.s_min_price IS NULL OR s.s_min_price=0), s.s_min_price, s.s_id LIMIT 40"
        ),
        {"id": str(v["vendor_id"]), **s_params},
    ).mappings().all()
    services = []
    for r in rows:
        pr = service_pricing(db, r, lang)
        if not pr["units"]:
            continue  # sans prix : "sur devis" (pas reservable en ligne)
        services.append({"id": r["s_id"], "title": r["s_title"], "description": " ".join((r["s_desp"] or "").split())[:300] or None, **pr})
    now = local_now()
    all_ranges, all_booked = load_availability(db, [v["vendor_id"]], now)
    slots = [{"iso": d.isoformat(), "label": slot_label(d, now, lang)} for d in compute_slots(all_ranges.get(v["vendor_id"], []), all_booked.get(v["vendor_id"], set()), now, days=7)][:8]
    return {
        "vendor_id": v["vendor_id"],
        "name": v["vendor_name"],
        "city": v["vendor_address_city"],
        "services": services,
        "linking_amount": linking_amount(db, v["vendor_mark"]),
        "districts": _districts_of(db, v["vendor_address_city"]),
        "slots": slots,
        "payment": {"cash": True, "online": online_available()},
        "max_days_ahead": settings.booking_max_days_ahead,
    }


# --------------------------------------------------------------------------- coupon + prix
def coupon_for(db: Session, code: str | None) -> dict | None:
    """Coupon valide : meme regle que le backend Node (`c_usedby = '0'`) + actif."""
    code = (code or "").strip()
    if not code:
        return None
    row = db.execute(text("SELECT cp_id, c_code, c_type, c_value FROM coupons WHERE c_code=:c AND c_usedby='0' AND c_isactive=1 LIMIT 1"), {"c": code[:25]}).mappings().first()
    return dict(row) if row else None


def compute_price(base: int, qty: int, options_total: int, linking: int, coupon: dict | None) -> dict:
    subtotal = base * qty + options_total + linking  # comme `calculateTotalWithOptions` du site
    discount = 0
    if coupon:
        try:
            value = float(coupon["c_value"])
        except (TypeError, ValueError):
            value = 0.0
        if coupon["c_type"] == "percentage":
            discount = int(round(subtotal * min(max(value, 0), 100) / 100))
        elif coupon["c_type"] == "flat":
            discount = int(min(max(value, 0), subtotal))
    return {"service": base * qty, "options": options_total, "linking": linking, "subtotal": subtotal, "discount": discount, "total": max(0, subtotal - discount)}


def _pick_service(db: Session, vendor: dict, service_id: int, unit_id: str | None, option_names: list[str], lang: str, country: str):
    s_clause, s_params = service_country_clause(db, country, "services")
    row = db.execute(
        text(f"SELECT s_id, s_title, s_desp, s_min_price, s_sub_services, s_options, s_subcat_id FROM services WHERE s_id=:i AND s_vendor_id=:v AND s_is_active='1' AND {s_clause}"),
        {"i": service_id, "v": str(vendor["vendor_id"]), **s_params},
    ).mappings().first()
    if not row:
        raise BookingError(404, "Service introuvable pour ce prestataire.")
    pr = service_pricing(db, row, lang)
    if not pr["units"]:
        raise BookingError(422, "Ce service est sur devis : demandez un devis au prestataire.")
    unit = next((u for u in pr["units"] if u["unit_id"] == str(unit_id)), None) if unit_id is not None else pr["units"][0]
    if unit is None:
        raise BookingError(422, "Formule de prix inconnue pour ce service.")
    chosen = []
    for name in dict.fromkeys(option_names):
        opt = next((o for o in pr["options"] if o["name"] == name), None)
        if opt is None:
            raise BookingError(422, f"Option inconnue : {name[:40]}.")
        chosen.append(opt)
    return row, unit, chosen


def quote(db: Session, ref: str, service_id: int, unit_id: str | None, qty: int, option_names: list[str], coupon_code: str | None, lang: str = "fr", country: str = "TG") -> dict:
    v = listed_vendor(db, ref, country)
    if v is None:
        raise BookingError(404, "Prestataire introuvable.")
    _, unit, chosen = _pick_service(db, v, service_id, unit_id, option_names, lang, country)
    coupon = coupon_for(db, coupon_code)
    if (coupon_code or "").strip() and coupon is None:
        raise BookingError(422, "Code promo invalide ou deja utilise.", "bad_coupon")
    price = compute_price(unit["price"], qty, sum(o["price"] for o in chosen), linking_amount(db, v["vendor_mark"]), coupon)
    price["coupon"] = {"code": coupon["c_code"], "type": coupon["c_type"], "value": coupon["c_value"]} if coupon else None
    return price


# --------------------------------------------------------------------------- creation
def _generate_code(db: Session) -> str:
    for _ in range(20):
        code = "TB" + str(100000 + secrets.randbelow(900000))
        if not db.execute(text("SELECT 1 FROM bookings WHERE bk_unique_id=:c"), {"c": code}).first():
            return code
    raise BookingError(503, "Impossible de generer la reference de reservation. Reessayez.")


def validate_when(day: date, hhmm: str) -> None:
    if not _TIME.match(hhmm or ""):
        raise BookingError(422, "Heure invalide (format HH:MM).")
    now = local_now()
    start = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
    if start < now + timedelta(minutes=30):
        raise BookingError(422, "Choisissez un horaire dans le futur (au moins 30 minutes).")
    if day > now.date() + timedelta(days=settings.booking_max_days_ahead):
        raise BookingError(422, f"Reservation possible jusqu'a {settings.booking_max_days_ahead} jours a l'avance.")


def validate_location(db: Session, vendor: dict, data: dict) -> dict:
    link = (data.get("link") or "").strip() or None
    if link and not _MAPS.match(link):
        raise BookingError(422, "Le lien doit etre un lien Google Maps (https://maps.app.goo.gl/… ou google.com/maps…).")
    lat, lng = data.get("latitude"), data.get("longitude")
    if (lat is None) != (lng is None):
        raise BookingError(422, "Position incomplete.")
    if lat is not None and not (-90 <= float(lat) <= 90 and -180 <= float(lng) <= 180):
        raise BookingError(422, "Position GPS invalide.")
    district_id = data.get("district_id")
    districts = _districts_of(db, vendor["vendor_address_city"])
    if district_id is not None and districts and int(district_id) not in {d["id"] for d in districts}:
        raise BookingError(422, "Quartier inconnu pour cette ville.")
    if district_id is None and districts:
        raise BookingError(422, "Choisissez votre quartier.")
    return {"link": link, "latitude": lat, "longitude": lng, "district_id": int(district_id) if district_id is not None else None, "manual": 0 if (link or lat is not None) else 1}


def create_booking(db: Session, client, vendor: dict, payload: dict, price: dict, row, unit: dict, chosen: list[dict], loc: dict, day: date, ip: str | None) -> dict:
    """Enregistre la reservation (table partagee `bookings`) ou la confie au backend Trankyl s'il est configure."""
    ref_code = _generate_code(db)
    online = payload["payment"] == "online"
    services_json = json.dumps([{"unit_id": unit["unit_id"], "price": unit["price"], "unit": {}}])
    options_json = json.dumps(chosen) if chosen else None

    if settings.node_api_url:
        body = {
            "b_clientId": str(client.id), "b_vendorId": str(vendor["vendor_id"]), "b_selectedTime": payload["time"], "b_totalAmount": price["subtotal"],
            "b_amountpaid": 0, "b_AmountRemaining": price["total"], "b_IfCoupon": str(payload["_coupon_id"]) if payload.get("_coupon_id") else "", "b_couponCode": payload.get("coupon") or "",
            "b_date": day.isoformat(), "b_time": payload["time"], "b_address": payload["address"], "linking_amount": price["linking"], "b_additional_info": payload.get("info") or "",
            "invoice_mode": (payload.get("pay_mode") or "ALL") if online else "PL", "b_paymentMethod": "ligne" if online else "cash", "b_paymentStatus": "", "booking_paymentIdentifier": f"academy-{client.id}-{secrets.token_hex(6)}",
            "b_subcatid": str(row["s_subcat_id"]), "b_qty": payload["qty"], "b_services": json.loads(services_json), "b_additional_options": chosen,
            "b_districtid": str(loc["district_id"] or ""), "b_client_name": payload["name"], "b_client_phone": payload["phone"], "b_client_address": payload["address"],
            "b_service_id": str(row["s_id"]), "currency_id": "1", "vendor_currency_id": vendor.get("vendor_currency_id"), "b_link_geolocation": loc["link"],
            "b_longitude": loc["longitude"], "b_latitude": loc["latitude"], "b_if_manuel_adress": loc["manual"], "b_servicesddress": "", "vendor_price": 1, "plateform": "academy",
        }
        try:
            r = httpx.post(settings.node_api_url.rstrip("/") + "/booking/book", json=body, timeout=30)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise BookingError(502, "Le service de reservation est momentanement indisponible. Reessayez.") from e
        if r.status_code >= 400 or str(data.get("status")) != "200":
            raise BookingError(502, "La reservation n'a pas pu etre enregistree. Reessayez dans un instant.")
        return {"id": data.get("id"), "ref": data.get("booking_id"), "invoice": data.get("invoice"), "invoice_error": data.get("invoice_error")}

    now = datetime.utcnow()
    db.execute(
        text(
            "INSERT INTO bookings (bk_unique_id, bk_client_id, bk_vendor_id, bk_district_id, bk_client_name, bk_client_phone, bk_client_address, bk_additional_info, "
            "bk_selected_time, bk_total_amount, bk_amount_paid, bk_amount_remaining, bk_if_coupon, bk_coupon_code, bk_date, bk_time, bk_address, bk_latitude, bk_longitude, "
            "bk_street_name, bk_street_number, bk_postal_code, bk_if_manuel_adress, bk_link_geolocation, bk_payment_method, bk_payment_status, bk_payment_identifier, "
            "bk_sub_cat_id, bk_qty, bk_services, bk_service_id, bk_additional_options, bk_cash_status, bk_previous_additional_info, bk_previous_service_desp, bk_created_at, "
            "bk_linking_amount, bk_linking_payed, bk_plateform, bk_country, bk_city) VALUES "
            "(:code, :cid, :vid, :did, :name, :phone, :addr, :info, :time, :total, '0', :remaining, :ifc, :cc, :day, :time, :addr, :lat, :lng, :street, :num, :postal, :manual, "
            ":link, :pm, 0, :pid, :subcat, :qty, :services, :sid, :opts, '0', :pinfo, :ptitle, :now, :linking, 0, 'academy', :country, :city)"
        ),
        {
            "code": ref_code, "cid": client.id, "vid": vendor["vendor_id"], "did": loc["district_id"], "name": payload["name"], "phone": payload["phone"], "addr": payload["address"],
            "info": payload.get("info") or None, "time": payload["time"], "total": str(price["subtotal"]), "remaining": str(price["total"]),
            "ifc": str(payload["_coupon_id"]) if payload.get("_coupon_id") else "0", "cc": payload.get("coupon") or None, "day": day, "lat": loc["latitude"], "lng": loc["longitude"],
            "street": payload.get("street_name"), "num": payload.get("street_number"), "postal": payload.get("postal_code"), "manual": loc["manual"], "link": loc["link"],
            "pm": "ligne" if online else "cash", "pid": f"academy-{client.id}-{secrets.token_hex(6)}", "subcat": int(row["s_subcat_id"]) if str(row["s_subcat_id"]).isdigit() else None,
            "qty": str(payload["qty"]), "services": services_json, "sid": row["s_id"], "opts": options_json, "pinfo": "-".join((row["s_desp"] or "").split())[:2000],
            "ptitle": "-".join((row["s_title"] or "").split())[:500], "now": now, "linking": float(price["linking"]), "country": payload.get("country"), "city": payload.get("city"),
        },
    )
    bid = db.execute(text("SELECT bk_id FROM bookings WHERE bk_unique_id=:c"), {"c": ref_code}).scalar()
    db.commit()
    invoice, invoice_error = None, None
    if online:
        # La reservation est deja enregistree : un echec SEMOA ne la perd pas, le client peut relancer le paiement.
        try:
            mode = payload.get("pay_mode") if payload.get("pay_mode") in bp.MODES else "ALL"
            invoice = semoa.create_booking_invoice(
                db, booking_id=bid, booking_ref=ref_code, amount=bp.split(price["total"], price["linking"])[mode], phone=payload["phone"], name=payload["name"], vendor_id=vendor["vendor_id"], mode=mode,
            )
        except semoa.SemoaError as e:
            invoice_error = e.message
    return {"id": bid, "ref": ref_code, "invoice": invoice, "invoice_error": invoice_error}


# --------------------------------------------------------------------------- administration
STATUS_SQL = {
    "pending": "(b.bk_service_status IS NULL OR b.bk_service_status IN ('0','1'))",
    "completed": "b.bk_service_status = '2'",
    "cancelled": "b.bk_service_status IN ('3','4')",
}


def admin_scope(db: Session, country: str) -> tuple[str, dict]:
    """Reservations du pays de l'administrateur. Une reservation enregistree par Academy porte le code pays de son
    service (`bk_country`) ; les anciennes reservations sont rattachees au pays de leur service, a defaut de leur prestataire."""
    s_clause, s_params = service_country_clause(db, country, "s")
    v_clause, v_params = vendor_country_clause(db, country, "v")
    sql = f"(CASE WHEN CHAR_LENGTH(COALESCE(b.bk_country,'')) = 2 THEN b.bk_country = :b_cc WHEN s.s_id IS NOT NULL THEN ({s_clause}) ELSE ({v_clause}) END)"
    return sql, {"b_cc": country, **s_params, **v_params}


ADMIN_FROM = "FROM bookings b LEFT JOIN vendors v ON v.vendor_id=b.bk_vendor_id LEFT JOIN services s ON s.s_id=b.bk_service_id"
