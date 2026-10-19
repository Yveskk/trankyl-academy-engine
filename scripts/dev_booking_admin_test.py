"""E-mails de reservation (client + administration) et menu admin "Reservations".
Base DEV uniquement ; AUCUN e-mail reel n'est envoye (mode "log" : copie en memoire). Nettoie tout.

Usage : PYTHONPATH=. python3 scripts/dev_booking_admin_test.py"""
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
from sqlalchemy import bindparam, text  # noqa: E402

from app.api.v1.endpoints.directory import clear_directory_cache  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services import booking_mail  # noqa: E402
from app.services.mail import MailError  # noqa: E402
from app.services.security import delivery  # noqa: E402
from scripts._admin_login import admin_login_flow  # noqa: E402

limiter.enabled = False
settings.node_api_url = None
settings.admin_email = "ops@example.test, boss@example.test"
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
client_ids: list[int] = []
admin_emails: list[str] = []
role_ids: list[int] = []
A = "/api/v1/bookings"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:220]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    db.rollback()
    return db


def make_client(n):
    email = f"bka-{tag}-{n}@example.com"
    db.execute(text("INSERT INTO clients (client_unique_id, client_name, client_email, client_password, client_phone, client_is_active) VALUES (:u,:n,:e,:p,:ph,1)"), {"u": f"CLI{tag}{n}", "n": f"Cora Test{n}", "e": email, "p": hash_password("Zephyr-Mango-1!"), "ph": f"+22893{tag[:3].translate(str.maketrans('abcdef', '123456'))}{n:03d}"})
    db.commit()
    cid = fresh().execute(text("SELECT client_id FROM clients WHERE client_email=:e"), {"e": email}).scalar()
    client_ids.append(cid)
    return cid, email, lambda lang="fr": {"Authorization": "Bearer " + create_access_token(subject=str(cid), role="client"), "X-Lang": lang}


def mails(ref):
    return [m for m in delivery.OUTBOX if m.get("html") and ref in (m.get("subject") or "")]


try:
    clear_directory_cache()
    items = c.get("/api/v1/directory/search?limit=50&country=TG").json()["items"]
    opts = next((r.json() for it in items if (r := c.get(f"{A}/options/{it['vendor_id']}")).status_code == 200 and r.json()["services"]), None)
    check("un prestataire reservable existe", opts is not None)
    vid, svc = opts["vendor_id"], opts["services"][0]
    base = {"ref": str(vid), "service_id": svc["id"], "unit_id": svc["units"][0]["unit_id"], "qty": 2, "payment": "cash", "name": "Cora Test", "phone": "+22893000111", "address": "Nyekonakpoe <b>pres du marche</b>", "info": "<script>alert('x')</script> Sonner deux fois"}
    day = (datetime.utcnow() + timedelta(days=5)).date().isoformat()

    print("E-mails apres reservation")
    cid1, email1, H1 = make_client(1)
    delivery.OUTBOX.clear()
    r = c.post(A, headers=H1(), json={**base, "date": day, "time": "09:00"})
    check("reservation creee", r.status_code == 201, r.text)
    ref = r.json()["ref"]
    ms = mails(ref)
    to = sorted(m["destination"] for m in ms)
    check("3 e-mails : le client + les 2 adresses admin", to == sorted([email1, "ops@example.test", "boss@example.test"]), to)
    cm = next(m for m in ms if m["purpose"] == "booking_client")
    am = next(m for m in ms if m["purpose"] == "booking_admin")
    check("client : sujet avec la reference, en francais", ref in cm["subject"] and "enregistrée" in cm["subject"], cm["subject"])
    check("client : service, quantite, total, lien vers 'Mes reservations'", svc["title"] in cm["html"] and "× 2" in cm["html"] and "/client/reservations" in cm["html"] and "FCFA" in cm["html"])
    price = r.json()["price"]
    check("client : total exact", f"{price['total']:,}".replace(",", " ") + " FCFA" in cm["html"], price)
    check("admin : coordonnees du client + lien vers l'administration", "+22893000111" in am["html"] and email1 in am["html"] and "/admin/reservations" in am["html"])
    check("admin : sujet 'Nouvelle reservation'", "Nouvelle réservation" in am["subject"] and ref in am["subject"])
    check("modele HTML complet (marque, bouton, pied de page)", all(k in cm["html"] for k in ("Trankyl", "<table", "Voir ma réservation", "font-family")))
    check("saisies du client ECHAPPEES (pas de HTML / script injecte)", "<script>" not in cm["html"] and "<script>" not in am["html"] and "&lt;script&gt;" in am["html"] and "<b>pres" not in cm["html"])
    check("rien n'est reellement envoye en mode log", all(m["channel"] == "email" for m in ms))

    cid2, email2, H2 = make_client(2)
    delivery.OUTBOX.clear()
    r2 = c.post(A, headers=H2("en"), json={**base, "date": day, "time": "10:00"})
    cm2 = next(m for m in mails(r2.json()["ref"]) if m["purpose"] == "booking_client")
    check("client anglophone : e-mail en anglais", "confirmed" in cm2["subject"] and "View my booking" in cm2["html"], cm2["subject"])
    am2 = next(m for m in mails(r2.json()["ref"]) if m["purpose"] == "booking_admin")
    check("l'alerte admin reste en francais", "Nouvelle réservation" in am2["subject"])

    print("Un echec d'envoi ne bloque jamais la reservation")
    cid3, email3, H3 = make_client(3)
    settings.otp_delivery_mode = "live"
    real = booking_mail.send_email
    booking_mail.send_email = lambda *a, **k: (_ for _ in ()).throw(MailError("Mailjet indisponible (simule)"))
    try:
        r3 = c.post(A, headers=H3(), json={**base, "date": day, "time": "11:00"})
    finally:
        booking_mail.send_email = real
        settings.otp_delivery_mode = "log"
    check("reservation creee malgre l'echec d'envoi", r3.status_code == 201, r3.text)
    check("... et enregistree en base", fresh().execute(text("SELECT COUNT(*) FROM bookings WHERE bk_unique_id=:r"), {"r": r3.json()["ref"]}).scalar() == 1)
    settings.admin_email = None
    delivery.OUTBOX.clear()
    cid4, email4, H4 = make_client(4)
    r4 = c.post(A, headers=H4(), json={**base, "date": day, "time": "12:00"})
    purposes = sorted(m["purpose"] for m in mails(r4.json()["ref"]))
    check("sans ADMIN_EMAIL : le client est servi, pas d'erreur", r4.status_code == 201 and purposes == ["booking_client"], purposes)
    settings.admin_email = "ops@example.test"

    print("Menu admin : Reservations")
    sa = f"bka-{tag}-super@example.com"
    admin_emails.append(sa)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sup','Er',:e,:p,1)"), {"e": sa, "p": hash_password("Sup3r-Bka-Pass!")})
    db.commit()
    tok, _, _ = admin_login_flow(c, sa, "Sup3r-Bka-Pass!")
    AH = lambda country="TG": {"Authorization": f"Bearer {tok}", "X-Country": country}
    lst = c.get(f"{A}/admin?page_size=100", headers=AH()).json()
    mine_refs = {ref, r2.json()["ref"], r3.json()["ref"], r4.json()["ref"]}
    check("liste du Togo : nos reservations y sont", mine_refs <= {i["ref"] for i in lst["items"]}, lst["total"])
    check("compteurs par statut", lst["counts"]["all"] == lst["counts"]["pending"] + lst["counts"]["completed"] + lst["counts"]["cancelled"] and lst["counts"]["pending"] >= 4, lst["counts"])
    check("liste de Cote d'Ivoire : aucune de nos reservations (service togolais)", not (mine_refs & {i["ref"] for i in c.get(f"{A}/admin?page_size=100", headers=AH('CI')).json()["items"]}))
    one = c.get(f"{A}/admin?q={ref}", headers=AH()).json()
    check("recherche par reference", one["total"] == 1 and one["items"][0]["ref"] == ref and one["items"][0]["client_name"] == "Cora Test")
    check("recherche par telephone du client", c.get(f"{A}/admin?q=%2B22893000111", headers=AH()).json()["total"] >= 4)
    check("filtre par date", c.get(f"{A}/admin?date_from={day}&date_to={day}&page_size=100", headers=AH()).json()["total"] >= 4)
    check("date invalide -> 422", c.get(f"{A}/admin?date_from=hier", headers=AH()).status_code == 422)
    pg = c.get(f"{A}/admin?page_size=2&page=2", headers=AH()).json()
    check("pagination", pg["page"] == 2 and len(pg["items"]) == 2 and pg["total"] == lst["total"])
    det = c.get(f"{A}/admin/{r.json()['id']}", headers=AH()).json()
    check("detail : client, prestataire, adresse, prix, options, e-mail du client", det["ref"] == ref and det["client_email"] == email1 and det["address"].startswith("Nyekonakpoe") and det["vendor_name"] and det["service"] == svc["title"] and det["status"] == "pending", det)
    check("detail d'un autre pays -> 404", c.get(f"{A}/admin/{r.json()['id']}", headers=AH("CI")).status_code == 404)
    before = fresh().execute(text("SELECT COALESCE(vendor_jobs_count,0) FROM vendors WHERE vendor_id=:v"), {"v": vid}).scalar()
    done = c.post(f"{A}/admin/{r.json()['id']}/status", headers=AH(), json={"status": "completed"})
    after = fresh().execute(text("SELECT COALESCE(vendor_jobs_count,0) FROM vendors WHERE vendor_id=:v"), {"v": vid}).scalar()
    check("marquer terminee + compteur de missions du prestataire +1", done.status_code == 200 and after == before + 1, (before, after))
    check("statut 'completed' dans la liste, filtre par statut", any(i["ref"] == ref for i in c.get(f"{A}/admin?status=completed&page_size=100", headers=AH()).json()["items"]))
    check("une reservation terminee ne change plus -> 409", c.post(f"{A}/admin/{r.json()['id']}/status", headers=AH(), json={"status": "cancelled"}).status_code == 409)
    can = c.post(f"{A}/admin/{r2.json()['id']}/status", headers=AH(), json={"status": "cancelled", "reason": "Prestataire indisponible"})
    st = fresh().execute(text("SELECT bk_service_status, bk_if_cancelled, bk_cancellation_reason FROM bookings WHERE bk_id=:i"), {"i": r2.json()["id"]}).first()
    check("annulation par l'admin (statut 4 + motif)", can.status_code == 200 and tuple(st) == ("4", "1", "Prestataire indisponible"), tuple(st))
    check("statut invalide -> 422", c.post(f"{A}/admin/{r3.json()['id']}/status", headers=AH(), json={"status": "n'importe quoi"}).status_code == 422)
    check("le client voit l'annulation dans son historique", any(m["ref"] == r2.json()["ref"] and m["status"] == "cancelled" for m in c.get(f"{A}/mine", headers=H2()).json()))

    print("Permissions du menu")
    mk_role = lambda name, perms: c.post("/api/v1/access/roles", headers=AH(), json={"name": name, "permissions": perms, "countries": []}).json()
    r_view, r_none = mk_role(f"Lecture resa {tag}", ["academy.bookings.view"]), mk_role(f"Sans resa {tag}", ["academy.blog.view"])
    role_ids += [r_view["id"], r_none["id"]]

    def staff(n, role):
        email = f"bka-{tag}-s{n}@example.com"
        admin_emails.append(email)
        u = c.post("/api/v1/access/users", headers=AH(), json={"firstname": "Staff", "lastname": f"N{n}", "email": email, "role_id": role["id"], "countries": ["TG"]}).json()
        t, _, _ = admin_login_flow(c, email, u["invitation"]["temp_password"], new_password="Zephyr-Mango-Quartz-7!")
        return {"Authorization": f"Bearer {t}", "X-Country": "TG"}

    SV, SN = staff(1, r_view), staff(2, r_none)
    check("sans la permission 'Reservations' : 403", c.get(f"{A}/admin", headers=SN).status_code == 403)
    check("lecture seule : liste et detail autorises", c.get(f"{A}/admin", headers=SV).status_code == 200 and c.get(f"{A}/admin/{r3.json()['id']}", headers=SV).status_code == 200)
    check("lecture seule : changer le statut -> 403", c.post(f"{A}/admin/{r3.json()['id']}/status", headers=SV, json={"status": "completed"}).status_code == 403)
    check("sans jeton -> 401", c.get(f"{A}/admin").status_code == 401)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    for cid in client_ids:
        db.execute(text("DELETE FROM bookings WHERE bk_client_id=:i AND bk_plateform='academy'"), {"i": cid})
        db.execute(text("DELETE FROM academy_security_events WHERE role='client' AND account_id=:i"), {"i": cid})
        db.execute(text("DELETE FROM clients WHERE client_id=:i"), {"i": cid})
    aids = [r[0] for r in db.execute(text("SELECT us_id FROM users WHERE email IN :e").bindparams(bindparam("e", expanding=True)), {"e": admin_emails or [""]}).fetchall()]
    if aids:
        for q in ("DELETE FROM academy_admin_countries WHERE user_id IN :i", "DELETE FROM academy_admin_profiles WHERE user_id IN :i",
                  "DELETE FROM academy_account_security WHERE role='admin' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='admin' AND account_id IN :i",
                  "DELETE FROM academy_trusted_devices WHERE role='admin' AND account_id IN :i", "DELETE FROM users WHERE us_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": aids})
    for rid in role_ids:
        db.execute(text("DELETE FROM academy_role_countries WHERE role_id=:i"), {"i": rid})
        db.execute(text("DELETE FROM user_types WHERE ust_id=:i AND ust_id<>1"), {"i": rid})
    db.execute(text("DELETE FROM academy_verifications WHERE role='admin' AND account_id NOT IN (SELECT us_id FROM users)"))
    db.execute(text("DELETE FROM academy_security_events WHERE detail LIKE :t OR detail LIKE 'TB%'"), {"t": f"%{tag}%"})
    if "vid" in globals() and "before" in globals():
        db.execute(text("UPDATE vendors SET vendor_jobs_count=:b WHERE vendor_id=:v"), {"b": before, "v": vid})  # restitue le compteur modifie par le test
    db.commit()
    clear_directory_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
