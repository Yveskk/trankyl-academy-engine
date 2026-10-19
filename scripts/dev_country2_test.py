"""Multi-pays, partie 2 : prestataires / avis / apprenants (pays du prestataire), taxonomie, curriculum, blog,
statistiques d'impact et configuration des pays. Base DEV uniquement ; nettoie tout ce qu'il cree.

Usage : PYTHONPATH=. python3 scripts/dev_country2_test.py"""
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
from scripts._admin_login import admin_login_flow  # noqa: E402

limiter.enabled = False
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
A = "/api/v1/access"
created_emails: list[str] = []
created_roles: list[int] = []
created_articles: list[int] = []
created_metiers: list[tuple[str, int]] = []


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:200]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def H(tok, country=None):
    h = {"Authorization": f"Bearer {tok}"}
    if country:
        h["X-Country"] = country
    return h


try:
    sa_email = f"cy2-{tag}-super@example.com"
    created_emails.append(sa_email)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sup','Er',:e,:p,1)"), {"e": sa_email, "p": hash_password("Sup3r-Cy2-Pass!")})
    db.commit()
    tok, _, _ = admin_login_flow(c, sa_email, "Sup3r-Cy2-Pass!")
    TG, CI = H(tok, "TG"), H(tok, "CI")

    print("Prestataires / avis / apprenants : pays du prestataire")
    ids = lambda r: {x["vendor_id"] if "vendor_id" in x else x["id"] for x in r.json()}
    p_tg = c.get("/api/v1/providers/admin?only_certified=false&limit=200", headers=TG)
    p_ci = c.get("/api/v1/providers/admin?only_certified=false&limit=200", headers=CI)
    check("listes prestataires 200", p_tg.status_code == 200 and p_ci.status_code == 200, p_tg.text)
    s_tg, s_ci = ids(p_tg), ids(p_ci)
    check("aucun prestataire commun a TG et CI", not (s_tg & s_ci), s_tg & s_ci)
    rows = db.execute(text("SELECT vendor_id, vendor_country_id FROM vendors WHERE vendor_id IN :i").bindparams(bindparam("i", expanding=True)), {"i": list(s_tg | s_ci) or [0]}).fetchall()
    cty = {r[0]: r[1] for r in rows}
    check("chaque prestataire de TG est du pays 217 (ou sans pays)", all(cty[v] in (217, None) for v in s_tg), [cty[v] for v in s_tg if cty[v] not in (217, None)])
    check("chaque prestataire de CI est du pays 52", all(cty[v] == 52 for v in s_ci))
    if s_tg:
        vid = sorted(s_tg)[0]
        check("profil d'un prestataire TG lisible depuis TG", c.get(f"/api/v1/providers/admin/{vid}/profile", headers=TG).status_code == 200)
        check("... et introuvable depuis CI (404)", c.get(f"/api/v1/providers/admin/{vid}/profile", headers=CI).status_code == 404)
        check("... modification depuis CI refusee (404)", c.put(f"/api/v1/providers/admin/{vid}/availability", headers=CI, json=[]).status_code == 404)
    r_tg, r_ci = c.get("/api/v1/reviews/admin?limit=500", headers=TG).json(), c.get("/api/v1/reviews/admin?limit=500", headers=CI).json()
    check("avis : listes disjointes", not ({x["id"] for x in r_tg} & {x["id"] for x in r_ci}))
    if r_tg:
        check("moderer l'avis d'un autre pays -> 404", c.patch(f"/api/v1/reviews/admin/{r_tg[0]['id']}", headers=CI, json={"reply": "x"}).status_code == 404)
    l_tg, l_ci = c.get("/api/v1/matching/admin/apprenants", headers=TG).json(), c.get("/api/v1/matching/admin/apprenants", headers=CI).json()
    check("apprenants : listes disjointes", not ({x["id"] for x in l_tg} & {x["id"] for x in l_ci}))
    if l_tg:
        check("verification d'identite d'un apprenant d'un autre pays -> 404", c.patch(f"/api/v1/matching/admin/apprenants/{l_tg[0]['id']}/verification", headers=CI, json={"reference_notes": "x"}).status_code == 404)
    check("mises en relation / inscriptions : 200 par pays", all(c.get(u, headers=h).status_code == 200 for u in ("/api/v1/contact-requests/admin", "/api/v1/enrollments/niveaux") for h in (TG, CI)))
    st_tg, st_ci = c.get("/api/v1/stats/public", headers={"X-Country": "TG"}).json(), c.get("/api/v1/stats/public", headers={"X-Country": "CI"}).json()
    check("statistiques d'impact par pays (apprenants = ceux du pays)", st_tg["total_apprenants"] == len(l_tg) and st_ci["total_apprenants"] == len(l_ci), (st_tg["total_apprenants"], len(l_tg), st_ci["total_apprenants"], len(l_ci)))

    print("Taxonomie / curriculum par pays")
    mk = lambda country, code: c.post("/api/v1/taxonomy/metiers", headers=H(tok, country), json={"code": code, "nom": f"Metier {code}", "description": "d", "nom_en": None, "description_en": None, "is_active": True})
    code = f"cy2-{tag}"
    a, b = mk("TG", code), mk("CI", code)
    check("meme code de metier possible dans chaque pays", a.status_code == 201 and b.status_code == 201, (a.text, b.text))
    created_metiers += [(code, a.json()["id"]), (code, b.json()["id"])]
    check("doublon dans le meme pays refuse", mk("TG", code).status_code == 400)
    tg_id, ci_id = a.json()["id"], b.json()["id"]
    pub = lambda country: [m["code"] for m in c.get(f"/api/v1/taxonomy/metiers?country={country}").json()]
    check("liste publique par pays", code in pub("TG") and code in pub("CI") and code not in pub("BJ"))
    check("detail public d'un metier : seulement dans son pays", c.get(f"/api/v1/taxonomy/metiers/{code}?country=CI").status_code == 200 and c.get(f"/api/v1/taxonomy/metiers/{code}?country=BJ").status_code == 404)
    check("admin CI voit son metier mais pas celui de TG", ci_id in {m["id"] for m in c.get("/api/v1/taxonomy/admin/metiers", headers=CI).json()} and tg_id not in {m["id"] for m in c.get("/api/v1/taxonomy/admin/metiers", headers=CI).json()})
    check("modifier un metier d'un autre pays -> 404", c.put(f"/api/v1/taxonomy/metiers/{tg_id}", headers=CI, json={"code": code, "nom": "x", "description": None, "nom_en": None, "description_en": None, "is_active": True}).status_code == 404)
    check("niveau d'un metier d'un autre pays -> 404", c.post(f"/api/v1/taxonomy/metiers/{tg_id}/niveaux", headers=CI, json={"numero": 1, "nom": "n", "description": None, "nom_en": None, "description_en": None, "date_debut": None}).status_code == 404)
    nv = c.post(f"/api/v1/taxonomy/metiers/{ci_id}/niveaux", headers=CI, json={"numero": 1, "nom": "N1", "description": None, "nom_en": None, "description_en": None, "date_debut": None})
    check("niveau cree dans le pays du metier", nv.status_code == 201, nv.text)
    cp = c.post(f"/api/v1/taxonomy/niveaux/{nv.json()['id']}/competences", headers=CI, json={"code": f"cmp-{tag}", "titre": "C", "description": None, "ordre": 1})
    check("competence creee", cp.status_code == 201, cp.text)
    check("module d'une competence d'un autre pays -> 404", c.post("/api/v1/curriculum/modules", headers=TG, json={"competence_id": cp.json()["id"], "code": f"mod-{tag}", "titre": "T", "contenu": "c", "duree_heures": 1, "ordre": 1}).status_code == 404)
    md = c.post("/api/v1/curriculum/modules", headers=CI, json={"competence_id": cp.json()["id"], "code": f"mod-{tag}", "titre": "T", "contenu": "c", "duree_heures": 1, "ordre": 1})
    check("module cree dans le bon pays", md.status_code == 201, md.text)
    check("suppression du module depuis un autre pays -> 404", c.delete(f"/api/v1/curriculum/modules/{md.json()['id']}", headers=TG).status_code == 404)
    check("suppression depuis son pays", c.delete(f"/api/v1/curriculum/modules/{md.json()['id']}", headers=CI).status_code == 204)

    print("Blog par pays")
    art = lambda country: c.post("/api/v1/blog/articles", headers=H(tok, country), json={"title": f"Art {country} {tag}", "excerpt": "e", "category": "t", "cover_image_url": None, "event_start_date": "2026-11-01", "event_end_date": "2026-11-02", "content": ["p"]})
    a_tg, a_ci = art("TG"), art("CI")
    check("articles crees", a_tg.status_code == 201 and a_ci.status_code == 201, a_ci.text)
    created_articles += [a_tg.json()["id"], a_ci.json()["id"]]
    titles = lambda country: [x["title"] for x in c.get(f"/api/v1/blog/articles?country={country}").json()]
    check("blog public TG : son article, pas celui de CI", f"Art TG {tag}" in titles("TG") and f"Art CI {tag}" not in titles("TG"))
    check("blog public CI : son article, pas celui de TG", f"Art CI {tag}" in titles("CI") and f"Art TG {tag}" not in titles("CI"))
    check("article de CI introuvable depuis TG (public + admin)", c.get(f"/api/v1/blog/articles/{a_ci.json()['id']}?country=TG").status_code == 404 and c.get(f"/api/v1/blog/admin/articles/{a_ci.json()['id']}", headers=TG).status_code == 404)
    check("modifier / supprimer depuis un autre pays -> 404", c.delete(f"/api/v1/blog/articles/{a_ci.json()['id']}", headers=TG).status_code == 404)
    check("articles historiques (sans pays) restent au Togo", all(isinstance(x["id"], int) for x in c.get("/api/v1/blog/admin/articles", headers=TG).json()))

    print("Configuration des pays")
    role = c.post(f"{A}/roles", headers=TG, json={"name": f"Config {tag}", "permissions": ["academy.config.manage", "academy.users.create"], "countries": ["CI"]})
    check("role cree", role.status_code == 201, role.text)
    created_roles.append(role.json()["id"])
    m_email = f"cy2-{tag}-ci@example.com"
    created_emails.append(m_email)
    r = c.post(f"{A}/users", headers=CI, json={"firstname": "A", "lastname": "B", "email": m_email, "role_id": role.json()["id"], "countries": ["CI"]})
    check("utilisateur CI cree", r.status_code == 201, r.text)
    mtok, _, _ = admin_login_flow(c, m_email, r.json()["invitation"]["temp_password"], new_password="Cfg-Ci-" + tag + "-Zx!")
    M = H(mtok, "CI")
    rc = c.get("/api/v1/config/countries", headers=M)
    check("admin CI : ne voit que son pays dans la liste des pays", rc.status_code == 200 and [x["code"] for x in rc.json()] in (["CI"], []), rc.text)
    check("admin CI : creer un pays refuse (403)", c.post("/api/v1/config/countries", headers=M, json={"code": "ML", "name": "Mali"}).status_code == 403)
    check("admin CI : reordonner / initialiser refuses (403)", c.post("/api/v1/config/countries/reorder", headers=M, json={"ids": []}).status_code == 403 and c.post("/api/v1/config/countries/initialize", headers=M).status_code == 403)
    check("super-admin : liste complete des pays", c.get("/api/v1/config/countries", headers=TG).status_code == 200)
    check("recherche publique : l'en-tete pays suffit", c.get("/api/v1/directory/search", headers={"X-Country": "CI"}).status_code == 200)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    for aid in created_articles:
        db.execute(text("DELETE FROM academy_entity_countries WHERE entity_type='blog' AND entity_id=:i"), {"i": aid})
        db.execute(text("DELETE FROM events WHERE event_id=:i"), {"i": aid})
    for code, mid in created_metiers:
        db.execute(text("DELETE FROM academy_competences WHERE niveau_id IN (SELECT id FROM academy_niveaux WHERE metier_id=:m)"), {"m": mid})
        db.execute(text("DELETE FROM academy_niveaux WHERE metier_id=:m"), {"m": mid})
        db.execute(text("DELETE FROM academy_metiers WHERE id=:m"), {"m": mid})
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
    db.commit()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
