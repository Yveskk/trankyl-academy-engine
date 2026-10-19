"""Prestataire SANS certificat : inscription dediee, visibilite apres verification, pays enregistre a l'inscription.
Base DEV uniquement ; nettoie tout ce qu'il cree.

Usage : PYTHONPATH=. python3 scripts/dev_provider_test.py"""
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce n'est pas une base dev.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import bindparam, text  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.home import invalidate_home_cache  # noqa: E402
from app.api.v1.endpoints.directory import clear_directory_cache  # noqa: E402
from app.services.security import delivery  # noqa: E402
from scripts._admin_login import admin_login_flow  # noqa: E402

limiter.enabled = False
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
vendor_emails: list[str] = []
client_emails: list[str] = []
admin_emails: list[str] = []
PW = "Zephyr-Mango-" + tag + "!"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:200]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    db.rollback()
    return db


def phone(n):
    return f"+22890{tag[:3].translate(str.maketrans('abcdef', '123456'))}{n:03d}"


def signup(payload, country="TG"):
    r = c.post("/api/v1/auth/signup/start", json=payload, headers={"X-Country": country})
    if r.status_code != 200:
        return r, None
    code = delivery.OUTBOX[-1]["code"]
    v = c.post("/api/v1/auth/signup/verify", json={"request_id": r.json()["request_id"], "code": code}, headers={"X-Country": country})
    return r, v


def search_ids(country="TG"):
    clear_directory_cache()
    r = c.get(f"/api/v1/directory/search?limit=50&country={country}")
    data = r.json()
    items = data.get("results") or data.get("providers") or data.get("items") or []
    return {(x.get("vendor_id") or x.get("id")): x for x in items}


try:
    admin_email = f"prv-{tag}-super@example.com"
    admin_emails.append(admin_email)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sup','Er',:e,:p,1)"), {"e": admin_email, "p": hash_password("Sup3r-Prv-Pass!")})
    db.commit()
    tok, _, _ = admin_login_flow(c, admin_email, "Sup3r-Prv-Pass!")
    AH = {"Authorization": f"Bearer {tok}", "X-Country": "TG"}

    print("Catalogue des metiers")
    cats = c.get("/api/v1/directory/categories").json()["categories"]
    check("metiers disponibles pour l'inscription", len(cats) > 0 and {"id", "name"} <= set(cats[0]), cats[:1])

    print("Inscription prestataire")
    base = {"role": "prestataire", "firstname": "Prune", "lastname": f"Plombier{tag}", "email": f"prv-{tag}-p@example.com", "password": PW, "phone": phone(1), "channel": "email", "subcategory_id": cats[0]["id"], "city": "Lomé", "years_experience": 6}
    check("metier inconnu refuse", c.post("/api/v1/auth/signup/start", json={**base, "subcategory_id": 999999}).status_code == 422)
    check("metier et ville sont facultatifs (a completer plus tard)", c.post("/api/v1/auth/signup/check", json={**base, "subcategory_id": None, "metier": None, "city": None}).status_code == 200)
    vendor_emails.append(base["email"])
    r, v = signup(base)
    check("code envoye puis compte cree (aucun certificat demande)", r.status_code == 200 and v is not None and v.status_code == 201 and v.json()["access_token"], v.text if v is not None else r.text)
    row = fresh().execute(text("SELECT vendor_id, vendor_academy_status, vendor_academy_verified, vendor_country_id, vendor_country_code, vendor_address_city FROM vendors WHERE vendor_email=:e"), {"e": base["email"]}).first()
    vid = row[0]
    check("statut 'provider', non verifie, pays Togo, ville enregistree", row[1] == "provider" and not row[2] and row[3] == 217 and row[4] == "TG" and row[5] == "Lomé", tuple(row))
    prof = db.execute(text("SELECT headline, years_experience FROM academy_provider_profiles WHERE vendor_id=:v"), {"v": vid}).first()
    check("profil : metier + experience", prof and prof[0] == cats[0]["name"] and prof[1] == 6, prof)
    check("meme espace de connexion que les apprenants", c.post("/api/v1/auth/login", json={"phone": base["phone"], "password": PW, "lang": "fr"}).status_code == 200)

    print("Visibilite")
    check("pas dans l'annuaire tant que l'equipe ne l'a pas verifie", vid not in search_ids("TG"))
    check("profil public introuvable avant verification", c.get(f"/api/v1/directory/providers/{vid}").status_code == 404)
    r = c.patch(f"/api/v1/matching/admin/apprenants/{vid}/verification", headers=AH, json={"is_verified": True})
    check("verification par un administrateur", r.status_code == 200, r.text)
    invalidate_home_cache()
    ids = search_ids("TG")
    check("apres verification : dans l'annuaire SANS certificat", vid in ids, list(ids)[:5])
    badges = (ids.get(vid) or {}).get("badges", {})
    check("badge 'Certifie' absent, 'Verifie' present", badges.get("certified") is False and badges.get("verified") is True, badges)
    check("profil public accessible", c.get(f"/api/v1/directory/providers/{vid}").status_code == 200)
    check("page Reserver (services) accessible", c.get(f"/api/v1/directory/providers/{vid}/services").status_code == 200)
    check("pas visible dans un autre pays (CI)", vid not in search_ids("CI"))
    ap = [x for x in c.get("/api/v1/matching/admin/apprenants", headers=AH).json() if x["id"] == vid]
    check("l'admin voit son statut 'provider'", ap and ap[0]["academy_status"] == "provider", ap)

    print("Les autres inscriptions ne changent pas")
    apb = {"role": "apprenant", "firstname": "Alix", "lastname": f"Apprenti{tag}", "email": f"prv-{tag}-a@example.com", "password": PW, "phone": phone(2), "channel": "email"}
    vendor_emails.append(apb["email"])
    r, v = signup(apb)
    arow = fresh().execute(text("SELECT vendor_id, vendor_academy_status FROM vendors WHERE vendor_email=:e"), {"e": apb["email"]}).first()
    check("apprenant : statut 'apprentice'", v.status_code == 201 and arow[1] == "apprentice")
    c.patch(f"/api/v1/matching/admin/apprenants/{arow[0]}/verification", headers=AH, json={"is_verified": True})
    check("un apprenant verifie mais non certifie n'est PAS liste", arow[0] not in search_ids("TG"))
    cb = {"role": "client", "firstname": "Cora", "lastname": f"Cliente{tag}", "email": f"prv-{tag}-c@example.com", "password": PW, "phone": phone(3), "channel": "email"}
    client_emails.append(cb["email"])
    r, v = signup(cb, country="CI")
    crow = fresh().execute(text("SELECT client_country_id, client_country_code FROM clients WHERE client_email=:e"), {"e": cb["email"]}).first()
    check("client inscrit en Cote d'Ivoire : pays enregistre", v.status_code == 201 and crow[0] == 52 and crow[1] == "CI", tuple(crow) if crow else None)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    vids = [r[0] for r in db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_email IN :e").bindparams(bindparam("e", expanding=True)), {"e": vendor_emails or [""]}).fetchall()]
    cids = [r[0] for r in db.execute(text("SELECT client_id FROM clients WHERE client_email IN :e").bindparams(bindparam("e", expanding=True)), {"e": client_emails or [""]}).fetchall()]
    if vids:
        for q in ("DELETE FROM academy_provider_profiles WHERE vendor_id IN :i", "DELETE FROM academy_trust_scores WHERE vendor_id IN :i",
                  "DELETE FROM academy_account_security WHERE role='apprenant' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='apprenant' AND account_id IN :i",
                  "DELETE FROM academy_trusted_devices WHERE role='apprenant' AND account_id IN :i", "DELETE FROM vendors WHERE vendor_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": vids})
    if cids:
        for q in ("DELETE FROM academy_account_security WHERE role='client' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='client' AND account_id IN :i",
                  "DELETE FROM academy_trusted_devices WHERE role='client' AND account_id IN :i", "DELETE FROM clients WHERE client_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": cids})
    aids = [r[0] for r in db.execute(text("SELECT us_id FROM users WHERE email IN :e").bindparams(bindparam("e", expanding=True)), {"e": admin_emails or [""]}).fetchall()]
    if aids:
        for q in ("DELETE FROM academy_admin_countries WHERE user_id IN :i", "DELETE FROM academy_admin_profiles WHERE user_id IN :i",
                  "DELETE FROM academy_account_security WHERE role='admin' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='admin' AND account_id IN :i",
                  "DELETE FROM academy_trusted_devices WHERE role='admin' AND account_id IN :i", "DELETE FROM users WHERE us_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": aids})
    db.execute(text("DELETE FROM academy_verifications WHERE destination LIKE :t"), {"t": f"%prv-{tag}%"})
    db.execute(text("DELETE FROM academy_security_events WHERE detail LIKE :t"), {"t": f"%{tag}%"})
    db.commit()
    invalidate_home_cache()
    clear_directory_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
