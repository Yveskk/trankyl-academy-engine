"""Test de la configuration admin des pays (base DEV uniquement ; nettoie ce
qu'il cree). Usage : python -m scripts.dev_config_test"""
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : base non dev.")

os.environ["OTP_DELIVERY_MODE"] = "log"  # aucun message reel pendant les tests

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.countries import invalidate_countries_cache  # noqa: E402
from app.services.home import invalidate_home_cache  # noqa: E402

c = TestClient(app)


from scripts._admin_login import admin_token  # noqa: E402
db = SessionLocal()
fails: list[str] = []


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL"), label, (f"[{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(label)


if db.execute(text("SELECT COUNT(*) FROM academy_countries")).scalar():
    sys.exit("academy_countries n'est pas vide : test annule pour ne rien ecraser.")

email, pw = f"cfg-{uuid.uuid4().hex[:6]}@example.com", uuid.uuid4().hex
made_type = not db.execute(text("SELECT 1 FROM user_types WHERE ust_id=1")).first()
if made_type:
    db.execute(text("INSERT INTO user_types (ust_id, ust_wording, ust_description, ust_roles) VALUES (1,'Admin','test','[\"ADMIN\"]')"))
db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Cfg','Test',:e,:p,1)"), {"e": email, "p": hash_password(pw)})
db.commit()


def strip(lang="fr", country="TG"):
    invalidate_home_cache()
    return c.get(f"/api/v1/home?lang={lang}&country={country}").json()["sections"]["topbar"]["data"]


try:
    H = {"Authorization": "Bearer " + admin_token(c, email, pw)}
    A = "/api/v1/config/countries"

    print("Acces")
    check("sans token -> 401", c.get(A).status_code == 401)

    print("Etat initial (table vide = comportement historique)")
    check("liste vide", c.get(A, headers=H).json() == [])
    legacy = strip()
    check("bande verte = liste historique (TG, CI, BJ)", [x["code"] for x in legacy["countries"]] == ["TG", "CI", "BJ"], str(legacy))

    print("Initialisation")
    r = c.post(f"{A}/initialize", headers=H)
    check("initialize -> 3 pays", r.status_code == 200 and [x["code"] for x in r.json()] == ["TG", "CI", "BJ"], r.text[:200])
    check("Togo par defaut", [x["code"] for x in r.json() if x["is_default"]] == ["TG"])
    check("initialize idempotent", len(c.post(f"{A}/initialize", headers=H).json()) == 3)
    s = strip()
    check("bande verte lit la base", [x["code"] for x in s["countries"]] == ["TG", "CI", "BJ"] and s["default_country"] == "TG", str(s))
    check("anglais : Benin", next(x for x in strip("en")["countries"] if x["code"] == "BJ")["name"] == "Benin")
    check("paiement du Togo expose", "Mixx" in next(x for x in s["countries"] if x["code"] == "TG")["payment_text"])

    print("Creation / validation")
    r = c.post(A, headers=H, json={"code": "gh", "name": "Ghana", "name_en": "Ghana", "payment_text": "Paiement : MTN MoMo", "help_url": "https://wa.me/233000000"})
    check("creation (code normalise en GH, en derniere position)", r.status_code == 201 and r.json()["code"] == "GH" and r.json()["sort_order"] > 30, r.text[:200])
    gh = r.json()
    check("doublon -> 400", c.post(A, headers=H, json={"code": "GH", "name": "Ghana bis"}).status_code == 400)
    check("code invalide -> 422", c.post(A, headers=H, json={"code": "G1", "name": "X"}).status_code == 422)
    check("lien d'aide invalide -> 422", c.post(A, headers=H, json={"code": "NE", "name": "Niger", "help_url": "javascript:alert(1)"}).status_code == 422)
    check("pays marketplace inconnu -> 400", c.post(A, headers=H, json={"code": "NE", "name": "Niger", "marketplace_country_id": 99999999}).status_code == 400)
    check("nouveau pays visible sur le site avec son aide", any(x["code"] == "GH" and x["help_url"] for x in strip()["countries"]))
    check("liste marketplace (lecture seule)", len(c.get(f"{A}/marketplace?q=Togo", headers=H).json()) >= 1)

    print("Modification")
    gh["name"] = "Ghana (modifie)"
    r = c.put(f"{A}/{gh['id']}", headers=H, json={k: gh[k] for k in ("code", "name", "name_en", "marketplace_country_id", "calling_code", "currency_code", "payment_text", "payment_text_en", "help_url", "is_active", "is_default", "sort_order")})
    check("PUT", r.status_code == 200 and r.json()["name"] == "Ghana (modifie)", r.text[:200])
    r = c.put(f"{A}/{gh['id']}", headers=H, json={**{k: gh[k] for k in ("code", "name", "name_en", "payment_text", "help_url", "is_active", "sort_order")}, "is_default": True})
    ds = [x["code"] for x in c.get(A, headers=H).json() if x["is_default"]]
    check("un seul pays par defaut (GH)", ds == ["GH"], str(ds))
    r = c.put(f"{A}/{gh['id']}", headers=H, json={**{k: gh[k] for k in ("code", "name", "name_en", "payment_text", "help_url", "is_active", "sort_order")}, "is_default": False})
    check("retirer l'unique defaut -> 400", r.status_code == 400)
    ci = next(x for x in c.get(A, headers=H).json() if x["code"] == "CI")
    r = c.put(f"{A}/{ci['id']}", headers=H, json={"code": "CI", "name": ci["name"], "name_en": ci["name_en"], "is_active": False, "is_default": False})
    check("desactiver CI", r.status_code == 200)
    check("CI absent de la bande verte", "CI" not in [x["code"] for x in strip()["countries"]])

    print("Ordre")
    rows = c.get(A, headers=H).json()
    ids = [x["id"] for x in reversed(rows)]
    check("reorder", c.post(f"{A}/reorder", headers=H, json={"ids": ids}).status_code == 200)
    order = [x["code"] for x in strip()["countries"]]
    check("ordre applique sur le site", order == [x["code"] for x in reversed(rows) if x["is_active"]], str(order))

    print("Filtre pays de la recherche")
    r = c.get("/api/v1/directory/search?country=TG&q=plomberie")
    check("recherche TG fonctionne avec les pays configures", r.status_code == 200 and r.json()["total"] > 0, r.text[:120])
    check("pays sans lien marketplace -> pas de filtre (pas d'erreur)", c.get("/api/v1/directory/search?country=GH").status_code == 200)

    print("Suppression")
    r = c.delete(f"{A}/{gh['id']}", headers=H)
    check("DELETE (pays par defaut)", r.status_code == 204)
    left = c.get(A, headers=H).json()
    check("un nouveau defaut est designe", sum(1 for x in left if x["is_default"]) == 1 and "GH" not in [x["code"] for x in left], str([(x["code"], x["is_default"]) for x in left]))
    check("404 si absent", c.delete(f"{A}/{gh['id']}", headers=H).status_code == 404)
finally:
    db.execute(text("DELETE FROM academy_countries"))
    db.execute(text("DELETE FROM users WHERE email=:e"), {"e": email})
    if made_type:
        db.execute(text("DELETE FROM user_types WHERE ust_id=1"))
    db.commit()
    invalidate_countries_cache()
    invalidate_home_cache()
    db.close()

print()
print(f"{len(fails)} echec(s) : {fails}" if fails else "Tous les controles passent. Donnees de test nettoyees.")
sys.exit(1 if fails else 0)
