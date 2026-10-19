"""Test de bout en bout du multi-pays : contenu, acces admin, roles, langue.
Base DEV uniquement. Cree des comptes/contenus jetables (pays TG et CI) et NETTOIE tout.

Usage : PYTHONPATH=. python3 scripts/dev_country_test.py"""
import json
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce n'est pas une base dev.")
if os.environ.get("ALLOW_HOME_WIPE") != "1":
    sys.exit("Refus : ce test vide temporairement les affiches, bannieres et sections d'accueil de la base dev (les modifications faites dans "
             "l'admin pendant son execution seraient perdues). Relancez avec ALLOW_HOME_WIPE=1 si personne n'utilise la base.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import bindparam, text  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.home import invalidate_home_cache  # noqa: E402
from scripts._admin_login import admin_login_flow  # noqa: E402

limiter.enabled = False
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
A = "/api/v1/access"
created_emails: list[str] = []
created_roles: list[int] = []


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:200]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def H(tok, country=None):
    h = {"Authorization": f"Bearer {tok}"}
    if country:
        h["X-Country"] = country
    return h


def fresh():
    db.rollback()
    return db


def home(country, lang="fr", headers=None, params=True):
    url = "/api/v1/home" + (f"?lang={lang}&country={country}" if params else "")
    return c.get(url, headers=headers or {}).json()


saved_items = saved_sections = saved_banners = None
try:
    # etat initial : sauvegarde de ce qui existe (affiches d'essai, bannieres...) puis table rase des tests
    fresh()
    saved_items = [dict(r._mapping) for r in db.execute(text("SELECT * FROM academy_home_items")).fetchall()]
    saved_sections = [dict(r._mapping) for r in db.execute(text("SELECT * FROM academy_content_sections")).fetchall()]
    saved_banners = [dict(r._mapping) for r in db.execute(text("SELECT * FROM academy_banners")).fetchall()]
    db.execute(text("DELETE FROM academy_home_items"))
    db.execute(text("DELETE FROM academy_banners"))
    db.execute(text("DELETE FROM academy_content_sections WHERE `key` IN ('hero','hero_slides','topbar','popular_searches','home_careers')"))
    db.commit()
    invalidate_home_cache()

    sa_email = f"cty-{tag}-super@example.com"
    created_emails.append(sa_email)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sup','Er',:e,:p,1)"), {"e": sa_email, "p": hash_password("Sup3r-Cty-Pass!")})
    db.commit()
    tok, _, _ = admin_login_flow(c, sa_email, "Sup3r-Cty-Pass!")
    S, S_TG, S_CI = H(tok), H(tok, "TG"), H(tok, "CI")

    print("Profil : pays accessibles")
    me = c.get("/api/v1/auth/admin/me", headers=S).json()
    check("super-admin : acces a tous les pays", me["all_countries"] and me["default_country"], me)

    print("Contenu separe par pays")
    poster = lambda title: {"section_key": "hero_slides", "kind": "poster", "title": title, "image_url": "https://example.test/p.jpg", "link_url": "/x", "data": {}}
    r_tg = c.post("/api/v1/home/admin/items", headers=S_TG, json=poster("Affiche Togo"))
    r_ci = c.post("/api/v1/home/admin/items", headers=S_CI, json=poster("Affiche Cote d'Ivoire"))
    check("affiche creee dans chaque pays", r_tg.status_code == 201 and r_ci.status_code == 201, r_ci.text)
    titles = lambda country, **kw: [s["title"] for s in home(country, **kw)["sections"]["hero_slides"]["data"]["slides"]]
    check("accueil TG : seulement l'affiche du Togo", titles("TG") == ["Affiche Togo"], titles("TG"))
    check("accueil CI : seulement l'affiche de Cote d'Ivoire", titles("CI") == ["Affiche Cote d'Ivoire"], titles("CI"))
    check("accueil BJ : aucune affiche (autre pays, aucune donnee)", titles("BJ") == [], titles("BJ"))
    check("en-tete X-Country (sans parametre) equivalent au parametre", [s["title"] for s in c.get("/api/v1/home?lang=fr", headers={"X-Country": "CI"}).json()["sections"]["hero_slides"]["data"]["slides"]] == ["Affiche Cote d'Ivoire"])
    check("le parametre l'emporte sur l'en-tete", [s["title"] for s in c.get("/api/v1/home?lang=fr&country=TG", headers={"X-Country": "CI"}).json()["sections"]["hero_slides"]["data"]["slides"]] == ["Affiche Togo"])
    check("pays inconnu (public) : repli sur le pays par defaut, jamais d'erreur", c.get("/api/v1/home?country=ZZ").status_code == 200 and home("ZZ")["country"] in ("TG",), home("ZZ")["country"])
    cfg_tg = {s["key"]: s for s in c.get("/api/v1/home/admin/config", headers=S_TG).json()}
    check("admin TG ne voit que ses affiches", [i["title"] for i in cfg_tg["hero_slides"]["items"]] == ["Affiche Togo"])
    ci_id = r_ci.json()["id"]
    check("modifier l'element d'un autre pays -> 404", c.put(f"/api/v1/home/admin/items/{ci_id}", headers=S_TG, json={**{k: v for k, v in poster('x').items() if k != 'section_key'}, "sort_order": 0, "is_active": True}).status_code == 404)
    check("supprimer l'element d'un autre pays -> 404", c.delete(f"/api/v1/home/admin/items/{ci_id}", headers=S_TG).status_code == 404)
    check("pays inconnu cote admin -> 404", c.get("/api/v1/home/admin/config", headers=H(tok, "ZZ")).status_code == 404)

    print("Reglages de section par pays")
    sec = lambda country, title: c.put("/api/v1/home/admin/sections/hero", headers=H(tok, country), json={"title": title, "title_en": None, "subtitle": None, "subtitle_en": None, "payload": {}, "payload_en": {}, "is_active": True, "sort_order": 0})
    check("titre du hero propre a chaque pays", sec("TG", "Titre TG").status_code == 200 and sec("CI", "Titre CI").status_code == 200)
    check("accueil TG / CI : titres differents", home("TG")["sections"]["hero"]["title"] == "Titre TG" and home("CI")["sections"]["hero"]["title"] == "Titre CI")

    print("Contenu editorial par pays (repli sur TG)")
    c.put("/api/v1/content/admin/sections/home_careers", headers=S_TG, json={"title": "Carrieres TG", "is_active": True})
    check("pays sans contenu : repli sur le pays de reference", c.get("/api/v1/content/sections/home_careers?country=CI").json().get("title") == "Carrieres TG")
    c.put("/api/v1/content/admin/sections/home_careers", headers=S_CI, json={"title": "Carrieres CI", "is_active": True})
    check("puis contenu propre au pays", c.get("/api/v1/content/sections/home_careers?country=CI").json()["title"] == "Carrieres CI" and c.get("/api/v1/content/sections/home_careers?country=TG").json()["title"] == "Carrieres TG")

    print("Langue")
    en = c.get("/api/v1/home?country=TG", headers={"X-Lang": "en"}).json()
    check("en-tete X-Lang=en -> reponse en anglais", en["lang"] == "en")
    check("parametre lang=fr l'emporte", c.get("/api/v1/home?country=TG&lang=fr", headers={"X-Lang": "en"}).json()["lang"] == "fr")

    print("Utilisateurs lies a des pays")
    role = c.post(f"{A}/roles", headers=S_TG, json={"name": f"Global {tag}", "permissions": ["academy.home.manage", "academy.users.view", "academy.users.create", "academy.users.edit", "academy.users.suspend", "academy.posters.manage"]}).json()
    created_roles.append(role["id"])
    check("role sans pays = global", role["is_global"] and role["countries"] == [])
    role_ci = c.post(f"{A}/roles", headers=S_CI, json={"name": f"Seulement CI {tag}", "permissions": ["academy.posters.manage"], "countries": ["CI"]}).json()
    created_roles.append(role_ci["id"])
    check("role limite a CI", role_ci["countries"] == ["CI"], role_ci)
    names = lambda country: [r["name"] for r in c.get(f"{A}/roles", headers=H(tok, country)).json()]
    check("role CI invisible au Togo, visible en CI", f"Seulement CI {tag}" not in names("TG") and f"Seulement CI {tag}" in names("CI"))
    check("role global visible partout", f"Global {tag}" in names("TG") and f"Global {tag}" in names("CI"))

    mk = lambda email, countries, role_id=role["id"], country="TG", all_c=False: c.post(f"{A}/users", headers=H(tok, country), json={"firstname": "U", "lastname": "Ser", "email": email, "role_id": role_id, "countries": countries, "all_countries": all_c})
    check("sans pays precise : le pays courant est attribue par defaut", mk(f"cty-{tag}-none@example.com", []).status_code == 201)
    created_emails.append(f"cty-{tag}-none@example.com")
    check("pays inconnu refuse", mk(f"cty-{tag}-bad@example.com", ["ZZ"]).status_code == 422)
    m_email = f"cty-{tag}-mgr-ci@example.com"
    created_emails.append(m_email)
    r = mk(m_email, ["CI"], country="CI")
    check("gestionnaire limite a CI cree", r.status_code == 201, r.text)
    m_temp = r.json()["invitation"]["temp_password"]
    check("son profil : pays = CI uniquement", r.json()["user"]["countries"] == ["CI"] and not r.json()["user"]["all_countries"])
    mtok, _, _ = admin_login_flow(c, m_email, m_temp, new_password="Mgr-Ci-" + tag + "-Zx!")
    M = lambda country=None: H(mtok, country)
    me = c.get("/api/v1/auth/admin/me", headers=M()).json()
    check("/me : seulement CI", [x["code"] for x in me["countries"]] in (["CI"], []) and not me["all_countries"] and me["default_country"] == "CI", me)
    check("travaille en CI sans en-tete (pays par defaut = CI)", c.get("/api/v1/home/admin/config", headers=M()).status_code == 200)
    check("acces refuse au Togo (403)", c.get("/api/v1/home/admin/config", headers=M("TG")).status_code == 403)
    check("ecriture au Togo refusee (403)", c.post("/api/v1/home/admin/items", headers=M("TG"), json=poster("intrus")).status_code == 403)
    ci_cfg = c.get("/api/v1/home/admin/config", headers=M("CI")).json()
    check("en CI : voit les affiches de CI seulement", [i["title"] for s in ci_cfg if s["key"] == "hero_slides" for i in s["items"]] == ["Affiche Cote d'Ivoire"])
    check("liste des utilisateurs de CI : le gestionnaire s'y trouve", any(u["email"] == m_email for u in c.get(f"{A}/users", headers=M("CI")).json()))
    check("liste des utilisateurs : ceux du Togo seul ne sont pas visibles en CI", all(u["email"] != f"cty-{tag}-none@example.com" for u in c.get(f"{A}/users", headers=M("CI")).json()))
    check("creer un utilisateur au Togo : refuse", c.post(f"{A}/users", headers=M("CI"), json={"firstname": "a", "lastname": "b", "email": f"cty-{tag}-x1@example.com", "role_id": role["id"], "countries": ["TG"]}).status_code == 403)
    check("donner acces a tous les pays : refuse", c.post(f"{A}/users", headers=M("CI"), json={"firstname": "a", "lastname": "b", "email": f"cty-{tag}-x2@example.com", "role_id": role["id"], "all_countries": True}).status_code == 403)
    check("role limite a CI attribuable en CI", c.post(f"{A}/users", headers=M("CI"), json={"firstname": "a", "lastname": "b", "email": f"cty-{tag}-ci2@example.com", "role_id": role_ci["id"], "countries": ["CI"]}).status_code == 201)
    created_emails.append(f"cty-{tag}-ci2@example.com")
    # compte a deux pays : hors perimetre du gestionnaire CI
    two = f"cty-{tag}-two@example.com"
    created_emails.append(two)
    r = mk(two, ["TG", "CI"])
    two_id = r.json()["user"]["id"]
    check("compte TG+CI cree par un super-admin", r.status_code == 201 and set(r.json()["user"]["countries"]) == {"TG", "CI"}, r.text)
    check("visible en CI", any(u["id"] == two_id for u in c.get(f"{A}/users", headers=M("CI")).json()))
    check("mais le gestionnaire CI ne peut pas le suspendre (perimetre)", c.post(f"{A}/users/{two_id}/suspend", headers=M("CI")).status_code == 403)
    check("ni lui changer ses pays", c.put(f"{A}/users/{two_id}", headers=M("CI"), json={"firstname": "U", "lastname": "Ser", "role_id": role["id"], "countries": ["CI"]}).status_code == 403)
    check("le super-admin peut restreindre ses pays", c.put(f"{A}/users/{two_id}", headers=S_TG, json={"firstname": "U", "lastname": "Ser", "role_id": role["id"], "countries": ["CI"]}).json()["countries"] == ["CI"])
    check("devenu CI seul : plus visible au Togo, visible en CI", all(u["id"] != two_id for u in c.get(f"{A}/users", headers=S_TG).json()) and any(u["id"] == two_id for u in c.get(f"{A}/users", headers=S_CI).json()))
    check("et le gestionnaire CI peut maintenant le suspendre", c.post(f"{A}/users/{two_id}/suspend", headers=M("CI")).status_code == 200)

    print("Compte sans aucun pays")
    ghost = f"cty-{tag}-ghost@example.com"
    created_emails.append(ghost)
    r = mk(ghost, ["TG"])
    gid = r.json()["user"]["id"]
    db.execute(text("DELETE FROM academy_admin_countries WHERE user_id=:i"), {"i": gid})
    db.commit()
    check("connexion refusee : aucun pays attribue", c.post("/api/v1/auth/admin/login", json={"email": ghost, "password": r.json()["invitation"]["temp_password"]}).status_code == 403)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    ids = [r[0] for r in db.execute(text("SELECT us_id FROM users WHERE email IN :e").bindparams(bindparam("e", expanding=True)), {"e": created_emails or [""]}).fetchall()]
    if ids:
        for q in (
            "DELETE FROM academy_admin_countries WHERE user_id IN :i", "DELETE FROM academy_admin_profiles WHERE user_id IN :i",
            "DELETE FROM academy_account_security WHERE role='admin' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='admin' AND account_id IN :i",
            "DELETE FROM academy_trusted_devices WHERE role='admin' AND account_id IN :i", "DELETE FROM users WHERE us_id IN :i",
        ):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": ids})
    for rid in created_roles:
        db.execute(text("DELETE FROM academy_role_countries WHERE role_id=:i"), {"i": rid})
        db.execute(text("DELETE FROM user_types WHERE ust_id=:i AND ust_id<>1"), {"i": rid})
    db.execute(text("DELETE FROM academy_verifications WHERE role='admin' AND account_id NOT IN (SELECT us_id FROM users)"))
    db.execute(text("DELETE FROM academy_security_events WHERE detail LIKE :t"), {"t": f"%{tag}%"})
    db.execute(text("DELETE FROM academy_home_items"))
    db.execute(text("DELETE FROM academy_banners"))
    db.execute(text("DELETE FROM academy_content_sections WHERE `key` IN ('hero','hero_slides','topbar','popular_searches','home_careers')"))
    for table, rows in (("academy_content_sections", [r for r in (saved_sections or []) if r["key"] in ("hero", "hero_slides", "topbar", "popular_searches", "home_careers")]), ("academy_home_items", saved_items or []), ("academy_banners", saved_banners or [])):
        for row in rows:
            cols = ", ".join(f"`{k}`" for k in row)
            db.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({', '.join(':' + k for k in row)})"), row)
    db.commit()
    invalidate_home_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
