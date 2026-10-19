"""Le pays est porte par le SERVICE (colonne `services.s_country_id`) : un prestataire apparait dans un pays
s'il y publie un service ; chaque pays n'affiche que ses services. Base DEV uniquement ; nettoie tout.

Usage : PYTHONPATH=. python3 scripts/dev_service_country_test.py"""
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
from app.services.home import invalidate_home_cache  # noqa: E402
from scripts._admin_login import admin_login_flow  # noqa: E402

limiter.enabled = False
settings.node_api_url = None
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
service_ids: list[int] = []
vendor_ids: list[int] = []
client_ids: list[int] = []
admin_emails: list[str] = []
CI_TITLE = f"Service CI test {tag}"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:220]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    db.rollback()
    return db


def H(country):
    return {"X-Country": country}


def search(country):
    clear_directory_cache()
    d = c.get("/api/v1/directory/search?limit=50", headers=H(country)).json()
    return {(x.get("vendor_id") or x.get("id")): x for x in (d.get("items") or d.get("results") or [])}


try:
    clear_directory_cache()
    tg = search("TG")
    check("le Togo liste des prestataires", len(tg) > 0)
    vid = next(iter(tg))
    price_tg = tg[vid].get("price_from")
    ci_vid_before = search("CI")
    check("avant : aucun prestataire n'a de service en Cote d'Ivoire -> annuaire CI vide", len(ci_vid_before) == 0, list(ci_vid_before)[:5])

    # un service publie en Cote d'Ivoire (s_country_id = 52) par un prestataire deja liste au Togo
    db.execute(
        text(
            "INSERT INTO services (s_subcat_id, s_vendor_id, s_country_id, s_city_id, s_district_id, s_tools_used, s_title, s_desp, s_exp, s_sub_services, s_min_price, s_is_active, s_options) "
            "VALUES ('1', :v, '52', '1', '1', '-', :t, 'Service publie en Cote d''Ivoire', '-', '-', 100, '1', '-')"
        ),
        {"v": str(vid), "t": CI_TITLE},
    )
    db.commit()
    sid = fresh().execute(text("SELECT s_id FROM services WHERE s_title=:t"), {"t": CI_TITLE}).scalar()
    service_ids.append(sid)
    invalidate_home_cache()

    print("Annuaire : un prestataire est visible dans le pays de ses services")
    tg, ci = search("TG"), search("CI")
    check("prestataire toujours visible au Togo (ses services togolais)", vid in tg)
    check("et visible en Cote d'Ivoire (il y publie un service)", vid in ci, list(ci)[:5])
    check("les autres prestataires (services seulement au Togo) ne sont PAS en CI", set(ci) == {vid}, list(ci))
    price_ci = ci[vid].get("price_from")
    check("prix 'des' : CI = son service CI (100), TG n'est pas pollue par le service CI", price_ci == 100 and tg[vid].get("price_from") != 100 and tg[vid].get("price_from") == price_tg, (price_ci, tg[vid].get("price_from")))
    via_param = {x["vendor_id"] for x in c.get("/api/v1/directory/search?limit=50&country=CI").json()["items"]}
    check("en-tete X-Country et parametre ?country= equivalents", via_param == set(ci), via_param)

    print("Profil et services par pays")
    ptg = c.get(f"/api/v1/directory/providers/{vid}", headers=H("TG")).json()
    pci = c.get(f"/api/v1/directory/providers/{vid}", headers=H("CI")).json()
    titles = lambda p: [s["title"] for s in p["services"]]
    check("profil TG : services togolais seulement", CI_TITLE not in titles(ptg) and len(titles(ptg)) >= 1, titles(ptg))
    check("profil CI : uniquement le service ivoirien", titles(pci) == [CI_TITLE], titles(pci))
    other = next(v for v in tg if v != vid)
    check("prestataire sans service en CI : profil CI introuvable (404)", c.get(f"/api/v1/directory/providers/{other}", headers=H("CI")).status_code == 404)
    check("page Reserver (services) par pays", [s["title"] for s in c.get(f"/api/v1/directory/providers/{vid}/services", headers=H("CI")).json()["services"]] == [CI_TITLE])

    print("Reservation : le service doit etre publie dans le pays courant")
    ot, oc = c.get(f"/api/v1/bookings/options/{vid}", headers=H("TG")).json(), c.get(f"/api/v1/bookings/options/{vid}", headers=H("CI")).json()
    check("options TG sans le service CI ; options CI = le service CI", all(s["title"] != CI_TITLE for s in ot["services"]) and [s["title"] for s in oc["services"]] == [CI_TITLE], (ot["services"][:1], oc["services"]))
    check("prestataire sans service en CI : options CI -> 404", c.get(f"/api/v1/bookings/options/{other}", headers=H("CI")).status_code == 404)
    client_email = f"svc-{tag}@example.com"
    db.execute(text("INSERT INTO clients (client_unique_id, client_name, client_email, client_password, client_phone, client_is_active) VALUES (:u,'Cora Svc',:e,:p,'+22592000000',1)"), {"u": f"CLI{tag}", "e": client_email, "p": hash_password("Zephyr-Mango-1!")})
    db.commit()
    cid = fresh().execute(text("SELECT client_id FROM clients WHERE client_email=:e"), {"e": client_email}).scalar()
    client_ids.append(cid)
    CH = lambda country: {"Authorization": "Bearer " + create_access_token(subject=str(cid), role="client"), "X-Country": country}
    day = (datetime.utcnow() + timedelta(days=4)).date().isoformat()
    body = {"ref": str(vid), "service_id": sid, "qty": 1, "date": day, "time": "10:00", "name": "Cora Svc", "phone": "+22592000000", "address": "Plateau, Abidjan", "payment": "cash"}
    check("reserver le service CI depuis le Togo -> 404", c.post("/api/v1/bookings", headers=CH("TG"), json=body).status_code == 404)
    r = c.post("/api/v1/bookings", headers=CH("CI"), json=body)
    check("reserver le service CI depuis la Cote d'Ivoire -> 201", r.status_code == 201, r.text)
    row = fresh().execute(text("SELECT bk_country, bk_service_id FROM bookings WHERE bk_unique_id=:r"), {"r": r.json()["ref"]}).first()
    check("pays de la reservation = pays du service", row[0] == "CI" and row[1] == sid, tuple(row))

    print("Cote admin : prestataires du pays")
    sa = f"svc-{tag}-super@example.com"
    admin_emails.append(sa)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sup','Er',:e,:p,1)"), {"e": sa, "p": hash_password("Sup3r-Svc-Pass!")})
    db.commit()
    tok, _, _ = admin_login_flow(c, sa, "Sup3r-Svc-Pass!")
    AH = lambda country: {"Authorization": f"Bearer {tok}", "X-Country": country}
    ids = lambda country: {x["vendor_id"] for x in c.get("/api/v1/providers/admin?only_certified=false&limit=200", headers=AH(country)).json()}
    check("admin CI : le prestataire (service ivoirien) y est, pas les autres", vid in ids("CI") and other not in ids("CI"))
    check("admin TG : il y est aussi (ses services togolais)", vid in ids("TG") and other in ids("TG"))

    print("Prestataire sans aucun service : visible dans son pays d'inscription")
    db.execute(text("INSERT INTO vendors (vendor_unique_id, vendor_name, vendor_email, vendor_phone, vendor_is_active, vendor_academy_status, vendor_academy_verified, vendor_country_id, vendor_country_code, vendor_address_city, vendor_created_at) VALUES (:u,:n,'',:ph,'1','provider',1,217,'TG','Lome',NOW())"), {"u": f"VEN{tag}", "n": f"Nouveau Prest{tag}", "ph": f"+22893{tag[:3].translate(str.maketrans('abcdef', '123456'))}999"})
    db.commit()
    nvid = fresh().execute(text("SELECT vendor_id FROM vendors WHERE vendor_unique_id=:u"), {"u": f"VEN{tag}"}).scalar()
    vendor_ids.append(nvid)
    clear_directory_cache()
    check("liste en attente (sans service) : visible au Togo", nvid in search("TG"))
    check("... pas en Cote d'Ivoire", nvid not in search("CI"))
    check("... visible de l'equipe admin du Togo, pas de celle de CI", nvid in ids("TG") and nvid not in ids("CI"))
    db.execute(text("INSERT INTO services (s_subcat_id, s_vendor_id, s_country_id, s_city_id, s_district_id, s_tools_used, s_title, s_desp, s_exp, s_sub_services, s_min_price, s_is_active, s_options) VALUES ('1', :v, '52', '1', '1', '-', :t, 'x', '-', '-', 500, '1', '-')"), {"v": str(nvid), "t": f"Service CI nouveau {tag}"})
    db.commit()
    service_ids.append(fresh().execute(text("SELECT s_id FROM services WHERE s_title=:t"), {"t": f"Service CI nouveau {tag}"}).scalar())
    clear_directory_cache()
    check("des qu'il publie un service en CI : visible en CI et plus au Togo", nvid in search("CI") and nvid not in search("TG"))
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
    for sid_ in service_ids:
        db.execute(text("DELETE FROM services WHERE s_id=:i"), {"i": sid_})
    for v in vendor_ids:
        for q in ("DELETE FROM academy_provider_profiles WHERE vendor_id=:i", "DELETE FROM academy_trust_scores WHERE vendor_id=:i", "DELETE FROM vendors WHERE vendor_id=:i"):
            db.execute(text(q), {"i": v})
    aids = [r[0] for r in db.execute(text("SELECT us_id FROM users WHERE email IN :e").bindparams(bindparam("e", expanding=True)), {"e": admin_emails or [""]}).fetchall()]
    if aids:
        for q in ("DELETE FROM academy_admin_countries WHERE user_id IN :i", "DELETE FROM academy_admin_profiles WHERE user_id IN :i",
                  "DELETE FROM academy_account_security WHERE role='admin' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='admin' AND account_id IN :i",
                  "DELETE FROM academy_trusted_devices WHERE role='admin' AND account_id IN :i", "DELETE FROM users WHERE us_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": aids})
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
