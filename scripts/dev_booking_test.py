"""Reservation d'un prestataire : options, devis (prix recalcule cote serveur), creation, historique, annulation.
Base DEV uniquement ; nettoie tout ce qu'il cree (client, reservations, coupons).

Usage : PYTHONPATH=. python3 scripts/dev_booking_test.py"""
import os
import sys
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce n'est pas une base dev.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.v1.endpoints.directory import clear_directory_cache  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

limiter.enabled = False
from app.services import booking as _bk  # noqa: E402

ONLINE = _bk.online_available()
settings.node_api_url = None  # jamais d'appel au backend Trankyl pendant les tests
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
client_ids: list[int] = []
coupon_codes: list[str] = []
A = "/api/v1/bookings"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:220]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    db.rollback()
    return db


def make_client(n):
    email = f"bk-{tag}-{n}@example.com"
    db.execute(
        text("INSERT INTO clients (client_unique_id, client_name, client_email, client_password, client_phone, client_is_active) VALUES (:u,:n,:e,:p,:ph,1)"),
        {"u": f"CLI{tag}{n}", "n": f"Cora Test{n}", "e": email, "p": hash_password("Zephyr-Mango-1!"), "ph": f"+22891{tag[:3].translate(str.maketrans('abcdef', '123456'))}{n:03d}"},
    )
    db.commit()
    cid = fresh().execute(text("SELECT client_id FROM clients WHERE client_email=:e"), {"e": email}).scalar()
    client_ids.append(cid)
    return cid, {"Authorization": "Bearer " + create_access_token(subject=str(cid), role="client")}


try:
    clear_directory_cache()
    listed = c.get("/api/v1/directory/search?limit=50&country=TG").json()
    items = listed.get("items") or listed.get("results") or []
    opts = None
    for it in items:
        r = c.get(f"{A}/options/{it.get('vendor_id') or it.get('id')}")
        if r.status_code == 200 and r.json()["services"]:
            opts = r.json()
            break
    check("un prestataire reservable existe (service avec prix)", opts is not None, [i.get("id") for i in items][:5])
    if opts is None:
        raise SystemExit("Aucun prestataire reservable dans la base dev.")
    vid, svc = opts["vendor_id"], opts["services"][0]
    unit = svc["units"][0]

    print("Options de reservation")
    check("services avec prix, frais de mise en relation, paiement especes seulement", opts["linking_amount"] >= 0 and opts["payment"] == {"cash": True, "online": ONLINE}, opts["payment"])
    check("creneaux proposes", isinstance(opts["slots"], list))
    check("prestataire inconnu -> 404", c.get(f"{A}/options/99999999").status_code == 404)

    print("Devis : le prix est TOUJOURS calcule par le serveur")
    base = {"ref": str(vid), "service_id": svc["id"], "unit_id": unit["unit_id"], "qty": 1}
    q = c.post(f"{A}/quote", json=base).json()
    check("prix = service + mise en relation", q["service"] == unit["price"] and q["linking"] == opts["linking_amount"] and q["total"] == unit["price"] + opts["linking_amount"] and q["discount"] == 0, q)
    q2 = c.post(f"{A}/quote", json={**base, "qty": 3}).json()
    check("quantite x3", q2["service"] == unit["price"] * 3 and q2["total"] == unit["price"] * 3 + opts["linking_amount"], q2)
    pct, flat = f"PC{tag}".upper()[:10], f"FL{tag}".upper()[:10]
    for code, typ, val in ((pct, "percentage", "10"), (flat, "flat", "500")):
        db.execute(text("INSERT INTO coupons (c_code, c_type, c_maxuse, c_value, c_isactive, c_usedby, cp_created_at) VALUES (:c,:t,'1',:v,1,'0',NOW())"), {"c": code, "t": typ, "v": val})
        coupon_codes.append(code)
    db.commit()
    qp = c.post(f"{A}/quote", json={**base, "coupon": pct}).json()
    check("coupon pourcentage : -10 % du total", qp["discount"] == round(q["subtotal"] * 0.10) and qp["total"] == q["subtotal"] - qp["discount"], qp)
    qf = c.post(f"{A}/quote", json={**base, "coupon": flat}).json()
    check("coupon montant fixe : -500", qf["discount"] == 500 and qf["total"] == q["subtotal"] - 500, qf)
    r = c.post(f"{A}/quote", json={**base, "coupon": "FAUX-CODE"})
    check("coupon invalide refuse", r.status_code == 422 and r.json()["detail"]["code"] == "bad_coupon", r.text)
    db.execute(text("UPDATE coupons SET c_isactive=0 WHERE c_code=:c"), {"c": pct})
    db.commit()
    check("coupon desactive refuse", c.post(f"{A}/quote", json={**base, "coupon": pct}).status_code == 422)
    check("service d'un autre prestataire -> 404", c.post(f"{A}/quote", json={**base, "service_id": 99999999}).status_code == 404)
    check("formule de prix inconnue -> 422", c.post(f"{A}/quote", json={**base, "unit_id": "zzz"}).status_code == 422)
    check("option inconnue -> 422", c.post(f"{A}/quote", json={**base, "options": ["inexistante"]}).status_code == 422)
    check("quantite hors limites -> 422", c.post(f"{A}/quote", json={**base, "qty": 0}).status_code == 422 and c.post(f"{A}/quote", json={**base, "qty": 500}).status_code == 422)

    print("Creation de la reservation")
    cid, H = make_client(1)
    cid2, H2 = make_client(2)
    day = (datetime.utcnow() + timedelta(days=3)).date().isoformat()
    body = {**base, "qty": 2, "date": day, "time": "10:00", "name": "Cora Test", "phone": "+22891000111", "address": "Nyekonakpoe, pres du marche", "info": "Fuite sous l'evier", "payment": "cash", "coupon": flat}
    check("sans connexion -> 401", c.post(A, json=body).status_code == 401)
    r = c.post(A, headers=H, json=body)
    check("reservation creee", r.status_code == 201 and r.json()["ref"].startswith("TB") and r.json()["status"] == "pending", r.text)
    j = r.json()
    expect = unit["price"] * 2 + opts["linking_amount"]
    check("total recalcule par le serveur (jamais le client)", j["price"]["subtotal"] == expect and j["price"]["total"] == expect - 500, j["price"])
    row = fresh().execute(text("SELECT bk_client_id, bk_vendor_id, bk_service_id, bk_total_amount, bk_amount_remaining, bk_payment_method, bk_payment_status, bk_qty, bk_address, bk_client_name, bk_client_phone, bk_linking_amount, bk_plateform, bk_coupon_code, bk_if_manuel_adress, bk_date, bk_time FROM bookings WHERE bk_unique_id=:r"), {"r": j["ref"]}).mappings().first()
    check("ligne ecrite dans la table partagee (client, prestataire, service, montants)", row and row["bk_client_id"] == cid and row["bk_vendor_id"] == vid and row["bk_service_id"] == svc["id"] and row["bk_total_amount"] == str(expect) and row["bk_amount_remaining"] == str(expect - 500), dict(row) if row else None)
    check("especes, non paye, plateforme 'academy', coupon et mise en relation enregistres", row["bk_payment_method"] == "cash" and not row["bk_payment_status"] and row["bk_plateform"] == "academy" and row["bk_coupon_code"] == flat and float(row["bk_linking_amount"]) == opts["linking_amount"], dict(row))
    check("adresse manuelle (ni lien ni GPS) -> bk_if_manuel_adress = 1", row["bk_if_manuel_adress"] == 1 and row["bk_address"].startswith("Nyekonakpoe"))
    check("meme demande envoyee deux fois -> 409 (pas de doublon)", c.post(A, headers=H, json=body).status_code == 409)

    print("Controles de la demande")
    bad = lambda **kw: c.post(A, headers=H2, json={**body, "time": "11:00", **kw}).status_code
    check("date passee -> 422", bad(date=(datetime.utcnow() - timedelta(days=1)).date().isoformat()) == 422)
    check("date trop lointaine -> 422", bad(date=(datetime.utcnow() + timedelta(days=900)).date().isoformat()) == 422)
    check("heure invalide -> 422", bad(time="25:99") == 422)
    check("lien qui n'est pas Google Maps -> 422", bad(link="https://evil.example/phish") == 422)
    check("position GPS incomplete -> 422", bad(latitude=6.1) == 422)
    check("position GPS hors limites -> 422", bad(latitude=120.0, longitude=1.2) == 422)
    if not ONLINE:  # sans passerelle de paiement configuree (Semoa / backend Trankyl), le paiement en ligne est refuse
        check("paiement en ligne indisponible sans passerelle -> 422", bad(payment="online") == 422)
    check("telephone invalide -> 422", bad(phone="12") == 422)
    check("coupon invalide -> 422", bad(coupon="PASBON") == 422)
    ok_link = c.post(A, headers=H2, json={**body, "coupon": None, "time": "12:00", "link": "https://maps.app.goo.gl/AbCdEf123", "latitude": 6.13, "longitude": 1.22})
    check("lien Google Maps + position : acceptes (adresse non manuelle)", ok_link.status_code == 201, ok_link.text)
    rowl = fresh().execute(text("SELECT bk_if_manuel_adress, bk_link_geolocation, bk_latitude FROM bookings WHERE bk_unique_id=:r"), {"r": ok_link.json()["ref"]}).first()
    check("... enregistres tels quels", rowl[0] == 0 and rowl[1].startswith("https://maps.app.goo.gl/") and float(rowl[2]) == 6.13, tuple(rowl))
    orig_status = db.execute(text("SELECT vendor_academy_status FROM vendors WHERE vendor_id=:v"), {"v": vid}).scalar()
    orig_vendor = vid
    db.execute(text("UPDATE vendors SET vendor_academy_status='apprentice' WHERE vendor_id=:v"), {"v": vid})
    db.commit()
    clear_directory_cache()
    r404 = c.post(A, headers=H2, json={**body, "time": "13:00"}).status_code
    db.execute(text("UPDATE vendors SET vendor_academy_status=:s WHERE vendor_id=:v"), {"s": orig_status, "v": vid})
    db.commit()
    clear_directory_cache()
    check("prestataire non liste -> 404 (on ne reserve pas n'importe qui)", r404 == 404)

    print("Historique et annulation")
    mine = c.get(f"{A}/mine", headers=H).json()
    check("mes reservations : la mienne, en attente", any(m["ref"] == j["ref"] and m["status"] == "pending" and m["vendor_id"] == vid for m in mine), mine[:1])
    check("les reservations des autres ne sont pas visibles", all(m["ref"] != ok_link.json()["ref"] for m in mine))
    check("annuler la reservation d'un autre client -> 404", c.post(f"{A}/{j['id']}/cancel", headers=H2, json={}).status_code == 404)
    r = c.post(f"{A}/{j['id']}/cancel", headers=H, json={"reason": "Changement de programme"})
    check("annulation par son proprietaire", r.status_code == 200 and r.json()["status"] == "cancelled", r.text)
    st = fresh().execute(text("SELECT bk_service_status, bk_if_cancelled, bk_cancellation_reason FROM bookings WHERE bk_id=:i"), {"i": j["id"]}).first()
    check("statut '4' + motif (comme le backend Trankyl)", st[0] == "4" and st[1] == "1" and st[2] == "Changement de programme", tuple(st))
    check("annuler deux fois -> 409", c.post(f"{A}/{j['id']}/cancel", headers=H, json={}).status_code == 409)
    check("apres annulation : statut 'cancelled' dans l'historique", any(m["ref"] == j["ref"] and m["status"] == "cancelled" for m in c.get(f"{A}/mine", headers=H).json()))
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    if "orig_vendor" in globals():  # restitue le statut d'origine meme si le test a echoue entre-temps
        db.execute(text("UPDATE vendors SET vendor_academy_status=:s WHERE vendor_id=:v"), {"s": orig_status, "v": orig_vendor})
    for cid in client_ids:
        db.execute(text("DELETE FROM bookings WHERE bk_client_id=:i AND bk_plateform='academy'"), {"i": cid})
        db.execute(text("DELETE FROM academy_security_events WHERE role='client' AND account_id=:i"), {"i": cid})
        db.execute(text("DELETE FROM clients WHERE client_id=:i"), {"i": cid})
    for code in coupon_codes:
        db.execute(text("DELETE FROM coupons WHERE c_code=:c"), {"c": code})
    db.commit()
    clear_directory_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
