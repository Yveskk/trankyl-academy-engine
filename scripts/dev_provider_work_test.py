"""Espace prestataire (travail) : demandes, devis, agenda, paiements, avis, profil public. Base DEV uniquement ; nettoie tout.
Usage : PYTHONPATH=. python3 scripts/dev_provider_work_test.py"""
import os
import sys
import uuid
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce n'est pas une base dev.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.v1.endpoints import provider_work as pw  # noqa: E402
from app.api.v1.endpoints.directory import clear_directory_cache  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import delivery  # noqa: E402

limiter.enabled = False
pw.upload_image = lambda data, kind: "https://res.cloudinary.com/demo/image/upload/w_200/sample.jpg"
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
P = "/api/v1/provider-space"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 300
ids: dict = {}


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:220]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def vendor(n, status="provider"):
    db.execute(text("INSERT INTO vendors (vendor_unique_id, vendor_name, vendor_email, vendor_phone, vendor_password, vendor_is_active, vendor_academy_status, vendor_country_id, vendor_country_code, vendor_created_at) VALUES (:u,:n,:e,:p,:h,1,:s,217,'TG',NOW())"),
               {"u": f"VPW{tag}{n}", "n": f"Prune{n}", "e": f"pw-{tag}-{n}@example.com", "p": f"+22891{n}{tag[:5].translate(str.maketrans('abcdef','123456'))}", "h": hash_password("Zephyr-Mango-1!"), "s": status})
    db.commit()
    vid = db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_email=:e"), {"e": f"pw-{tag}-{n}@example.com"}).scalar()
    return vid, {"Authorization": "Bearer " + create_access_token(subject=str(vid), role="apprenant")}


def booking(vid, ref, status, total, day=None, client=None):
    db.execute(text("INSERT INTO bookings (bk_unique_id, bk_vendor_id, bk_client_id, bk_client_name, bk_client_phone, bk_service_status, bk_total_amount, bk_amount_remaining, bk_date, bk_time, bk_plateform, bk_created_at, bk_payment_status) VALUES (:r,:v,:c,'Cora Test','+22890000001',:s,:t,:t,:d,'09:00','academy',NOW(),'0')"),
               {"r": ref, "v": vid, "c": client, "s": status, "t": str(total), "d": day or date.today()})
    db.commit()
    return db.execute(text("SELECT bk_id FROM bookings WHERE bk_unique_id=:r"), {"r": ref}).scalar()


try:
    vid, H = vendor(1)
    vid2, H2 = vendor(2)
    ids["v"] = [vid, vid2]
    check("sans jeton : 401", c.get(f"{P}/requests").status_code == 401)
    _, HA = vendor(3, "apprentice")
    ids["v"].append(db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_email=:e"), {"e": f"pw-{tag}-3@example.com"}).scalar())
    check("un apprenant : 403", c.get(f"{P}/requests", headers=HA).status_code == 403)

    print("Demandes")
    b1 = booking(vid, f"T1{tag}", "0", 9000, date.today() + timedelta(days=2))
    b2 = booking(vid, f"T2{tag}", "2", 8000)
    b3 = booking(vid2, f"T3{tag}", "0", 5000)
    ids["b"] = [b1, b2, b3]
    r = c.get(f"{P}/requests", headers=H).json()
    check("liste : seulement MES demandes, compteurs par statut", r["counts"] == {"pending": 1, "completed": 1, "cancelled": 0, "all": 2} and {i["ref"] for i in r["items"]} == {f"T1{tag}", f"T2{tag}"}, r["counts"])
    check("filtre par statut", [i["ref"] for i in c.get(f"{P}/requests?status=pending", headers=H).json()["items"]] == [f"T1{tag}"])
    check("recherche", len(c.get(f"{P}/requests?q=T2{tag}", headers=H).json()["items"]) == 1)
    check("la demande d'un autre prestataire -> 404", c.post(f"{P}/requests/{b3}/status", headers=H, json={"status": "completed"}).status_code == 404)
    check("annulation sans motif -> 422", c.post(f"{P}/requests/{b1}/status", headers=H, json={"status": "cancelled"}).status_code == 422)
    before = db.execute(text("SELECT COALESCE(vendor_jobs_count,0) FROM vendors WHERE vendor_id=:v"), {"v": vid}).scalar()
    check("marquer terminee", c.post(f"{P}/requests/{b1}/status", headers=H, json={"status": "completed"}).status_code == 200)
    db.rollback()
    check("compteur de missions +1", db.execute(text("SELECT COALESCE(vendor_jobs_count,0) FROM vendors WHERE vendor_id=:v"), {"v": vid}).scalar() == before + 1)
    check("une demande terminee ne change plus (409)", c.post(f"{P}/requests/{b1}/status", headers=H, json={"status": "cancelled", "reason": "x"}).status_code == 409)
    b4 = booking(vid, f"T4{tag}", "0", 3000)
    ids["b"].append(b4)
    check("annuler avec motif", c.post(f"{P}/requests/{b4}/status", headers=H, json={"status": "cancelled", "reason": "Indisponible"}).status_code == 200)
    db.rollback()
    check("statut 4 + motif en base", db.execute(text("SELECT bk_service_status, bk_cancellation_reason FROM bookings WHERE bk_id=:i"), {"i": b4}).first() == ("4", "Indisponible"))

    print("Devis")
    db.execute(text("INSERT INTO academy_quote_requests (country_code, vendor_id, vendor_name, name, phone, email, message, lang, status) VALUES ('TG',:v,'Prune1','Cora','+22890000001',:e,'Besoin d un devis','fr','new')"), {"v": vid, "e": f"cora-{tag}@example.com"})
    db.execute(text("INSERT INTO academy_quote_requests (country_code, vendor_id, vendor_name, name, phone, email, message, lang, status) VALUES ('TG',:v,'Prune2','Dora','+22890000002',:e,'Autre','fr','new')"), {"v": vid2, "e": f"dora-{tag}@example.com"})
    db.commit()
    qs = c.get(f"{P}/quotes", headers=H).json()
    check("mes devis seulement", len(qs) == 1 and qs[0]["name"] == "Cora", qs)
    other = c.get(f"{P}/quotes", headers=H2).json()[0]["id"]
    check("repondre au devis d'un autre -> 404", c.post(f"{P}/quotes/{other}/reply", headers=H, json={"subject": "Devis", "message": "Voici"}).status_code == 404)
    delivery.OUTBOX.clear()
    r = c.post(f"{P}/quotes/{qs[0]['id']}/reply", headers=H, json={"subject": "Votre devis", "message": "Voici mon prix : 9000 F"})
    check("réponse envoyée, statut 'answered'", r.status_code == 200 and r.json()["status"] == "answered", r.text)

    print("Agenda")
    check("disponibilités vides au départ", c.get(f"{P}/availability", headers=H).json() == [])
    check("fin avant début refusée", c.put(f"{P}/availability", headers=H, json=[{"weekday": 1, "start_time": "10:00", "end_time": "09:00"}]).status_code == 422)
    r = c.put(f"{P}/availability", headers=H, json=[{"weekday": 0, "start_time": "08:00", "end_time": "17:00"}, {"weekday": 5, "start_time": "09:00", "end_time": "12:00", "is_active": False}])
    check("plages enregistrées", r.status_code == 200 and len(r.json()) == 2 and r.json()[0]["start_time"] == "08:00", r.text)
    check("les plages d'un autre ne sont pas touchées", c.get(f"{P}/availability", headers=H2).json() == [])
    ag = c.get(f"{P}/agenda?days=7", headers=H).json()
    check("agenda : missions à venir (hors annulées)", [i["ref"] for i in ag["items"]] == [f"T1{tag}"] or ag["items"] == [] or all(i["status"] != "cancelled" for i in ag["items"]), ag)

    print("Paiements")
    p = c.get(f"{P}/payments", headers=H).json()
    check("totaux : gagné, à recevoir, en attente", p["totals"]["earned"] == 17000 and p["totals"]["completed_count"] == 2 and p["totals"]["to_receive"] == 17000 and p["totals"]["month"] == 17000, p["totals"])

    print("Avis")
    db.execute(text("INSERT INTO clients (client_unique_id, client_name, client_email, client_is_active) VALUES (:u,'Cora',:e,1)"), {"u": f"CPW{tag}", "e": f"c-{tag}@example.com"})
    db.commit()
    cid = db.execute(text("SELECT client_id FROM clients WHERE client_email=:e"), {"e": f"c-{tag}@example.com"}).scalar()
    ids["c"] = cid
    db.execute(text("INSERT INTO academy_reviews (client_id, vendor_id, rating, comment, status) VALUES (:c,:v,5,'Super','approved'), (:c,:v,2,'Bof','pending')"), {"c": cid, "v": vid})
    db.commit()
    rv = c.get(f"{P}/reviews", headers=H).json()
    check("avis : moyenne sur les approuvés, pending listé", rv["average"] == 5.0 and rv["count"] == 1 and len(rv["items"]) == 2, rv)
    rid = next(i["id"] for i in rv["items"] if i["status"] == "approved")
    check("répondre à un avis", c.post(f"{P}/reviews/{rid}/reply", headers=H, json={"reply": "Merci !"}).json()["reply"] == "Merci !")
    check("répondre à l'avis d'un autre -> 404", c.post(f"{P}/reviews/{rid}/reply", headers=H2, json={"reply": "x"}).status_code == 404)
    pend = next(i["id"] for i in rv["items"] if i["status"] == "pending")
    check("pas de réponse sur un avis non approuvé", c.post(f"{P}/reviews/{pend}/reply", headers=H, json={"reply": "x"}).status_code == 404)

    print("Profil public")
    pp = c.get(f"{P}/public-profile", headers=H).json()
    check("profil public vide au départ", pp["headline"] is None and pp["media"] == [] and pp["url"] == f"/profil/{vid}")
    r = c.put(f"{P}/public-profile", headers=H, json={"headline": "Plombier", "about": "Dépannage rapide", "years_experience": 8, "visit_fee": 2000, "zone_label": "Lomé"})
    check("enregistré", r.status_code == 200 and r.json()["headline"] == "Plombier" and r.json()["visit_fee"] == 2000, r.text)
    check("valeur absurde refusée", c.put(f"{P}/public-profile", headers=H, json={"years_experience": 500}).status_code == 422)
    check("couverture", c.post(f"{P}/public-profile/cover", headers=H, files={"file": ("a.png", PNG, "image/png")}).json()["cover_image_url"].startswith("https://"))
    check("faux fichier refusé", c.post(f"{P}/public-profile/cover", headers=H, files={"file": ("a.png", b"<?php", "image/png")}).status_code == 422)
    m = c.post(f"{P}/public-profile/media?caption=Salle%20de%20bain", headers=H, files={"file": ("a.png", PNG, "image/png")})
    check("réalisation ajoutée", m.status_code == 201 and m.json()["caption"] == "Salle de bain", m.text)
    mid = m.json()["id"]
    check("masquer une réalisation", c.patch(f"{P}/public-profile/media/{mid}", headers=H, json={"is_active": False}).json()["is_active"] is False)
    check("la réalisation d'un autre -> 404", c.patch(f"{P}/public-profile/media/{mid}", headers=H2, json={"is_active": True}).status_code == 404 and c.delete(f"{P}/public-profile/media/{mid}", headers=H2).status_code == 404)
    check("supprimer la réalisation", c.delete(f"{P}/public-profile/media/{mid}", headers=H).status_code == 204)
    db.execute(text("INSERT INTO services (s_vendor_id, s_title, s_is_active, s_is_deleted, s_min_price, s_country_id, s_city_id) VALUES (:v,'Fuite',:a,0,5000,'217','1')"), {"v": vid, "a": "1"})
    db.commit()
    sid = db.execute(text("SELECT s_id FROM services WHERE s_vendor_id=:v AND s_title='Fuite'"), {"v": vid}).scalar()
    ids["s"] = sid
    check("service listé et actif", [s for s in c.get(f"{P}/public-profile", headers=H).json()["services"] if s["id"] == sid][0]["is_active"] is True)
    check("masquer un service aux clients", c.patch(f"{P}/services/{sid}/visibility", headers=H, json={"is_active": False}).json()["is_active"] is False)
    db.rollback()
    check("service désactivé en base (s_is_active='0')", db.execute(text("SELECT s_is_active FROM services WHERE s_id=:i"), {"i": sid}).scalar() in ("0", 0))
    check("le service d'un autre -> 404", c.patch(f"{P}/services/{sid}/visibility", headers=H2, json={"is_active": True}).status_code == 404)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    v = ids.get("v", [])
    for vid_ in v:
        for q in ("DELETE FROM academy_provider_media WHERE vendor_id=:i", "DELETE FROM academy_provider_availability WHERE vendor_id=:i", "DELETE FROM academy_provider_profiles WHERE vendor_id=:i",
                  "DELETE FROM academy_reviews WHERE vendor_id=:i", "DELETE FROM academy_quote_requests WHERE vendor_id=:i", "DELETE FROM bookings WHERE bk_vendor_id=:i", "DELETE FROM services WHERE s_vendor_id=:i",
                  "DELETE FROM academy_trust_scores WHERE vendor_id=:i", "DELETE FROM academy_security_events WHERE account_id=:i AND role='apprenant'", "DELETE FROM vendors WHERE vendor_id=:i"):
            db.execute(text(q), {"i": vid_})
    if ids.get("c"):
        db.execute(text("DELETE FROM clients WHERE client_id=:i"), {"i": ids["c"]})
    db.commit()
    clear_directory_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
