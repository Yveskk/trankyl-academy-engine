"""Test de bout en bout de la configuration d'accueil sur la base DEV
(refuse de tourner ailleurs). Cree un admin jetable, exerce les endpoints
publics et admin via TestClient, verifie que chaque ecriture est visible dans
GET /home, puis NETTOIE tout ce qu'il a cree.

ATTENTION — ce test VIDE toute la configuration d'accueil (affiches, cartes, sections) pendant son execution, puis la
remet a l'identique a la fin. Toute modification faite dans l'admin PENDANT qu'il tourne (affiche ajoutee, image
telechargee...) est PERDUE. Il ne se lance donc qu'avec ALLOW_HOME_WIPE=1, quand personne ne travaille sur la base dev.

Usage : ALLOW_HOME_WIPE=1 python -m scripts.dev_smoke_test
"""
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

db_name = os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0]
if not db_name.endswith("_dev_db"):
    sys.exit(f"Refus : '{db_name}' n'est pas une base dev.")

if os.environ.get("ALLOW_HOME_WIPE") != "1":
    sys.exit("Refus : ce test vide temporairement la configuration d'accueil de la base dev (les modifications faites dans l'admin "
             "pendant son execution seraient perdues). Relancez avec ALLOW_HOME_WIPE=1 si personne n'utilise la base.")

os.environ["OTP_DELIVERY_MODE"] = "log"  # aucun message reel pendant les tests

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


from scripts._admin_login import admin_token  # noqa: E402
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


db = SessionLocal()
created_user_type = False
if not db.execute(text("SELECT 1 FROM user_types WHERE ust_id=1")).first():
    db.execute(text("INSERT INTO user_types (ust_id, ust_wording, ust_description, ust_roles) VALUES (1,'Admin','test','[\"ADMIN\"]')"))
    created_user_type = True
email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
password = uuid.uuid4().hex
db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Smoke','Test',:e,:p,1)"), {"e": email, "p": hash_password(password)})
db.commit()
created_items: list[int] = []
# Config d'accueil existante (affiches d'essai, cartes...) : sauvegardee, videe pour les tests, puis REMISE telle quelle.
saved_home_items = [dict(r._mapping) for r in db.execute(text("SELECT * FROM academy_home_items")).fetchall()]
saved_home_sections = [dict(r._mapping) for r in db.execute(text("SELECT * FROM academy_content_sections WHERE `key` IN ('topbar','hero','hero_slides','popular_searches','stats','services','guarantees','how_it_works','top_providers','pro','academy','news','testimonials','partners','apps')")).fetchall()]
db.execute(text("DELETE FROM academy_home_items"))
db.execute(text("DELETE FROM academy_content_sections WHERE `key` IN ('topbar','hero','hero_slides','popular_searches','stats','services','guarantees','how_it_works','top_providers','pro','academy','news','testimonials','partners','apps')"))
db.commit()
# Approuver un avis recalcule le score de confiance du prestataire : on
# restaure ces lignes a la fin pour laisser la base dev exactement comme avant.
saved_trust = db.execute(text("SELECT id, score_pct, rules_score, rules_breakdown_json, llm_score, justification, computed_at FROM academy_trust_scores")).fetchall()
cleanup_sql: list[tuple[str, dict]] = [("DELETE FROM users WHERE email=:e", {"e": email})]
if created_user_type:
    cleanup_sql.insert(0, ("DELETE FROM user_types WHERE ust_id=1", {}))

try:
    H = {"Authorization": f"Bearer {admin_token(client, email, password)}"}
    check("login admin (mot de passe + code)", True)

    print("Public")
    r = client.get("/api/v1/home?lang=fr&country=TG")
    check("GET /home 200", r.status_code == 200)
    home = r.json()
    check("15 sections par defaut (dont hero_slides)", len(home["sections"]) == 15, str(len(home["sections"])))
    check("services auto depuis le catalogue", len(home["sections"]["services"]["items"]) > 0)
    check("mieux notes non vide", len(home["sections"]["top_providers"]["data"]["providers"]) > 0)
    check("ETag + Cache-Control", "etag" in r.headers and "max-age" in r.headers.get("cache-control", ""))
    check("304 si ETag identique", client.get("/api/v1/home?lang=fr&country=TG", headers={"If-None-Match": r.headers["etag"]}).status_code == 304)
    check("anglais traduit", client.get("/api/v1/home?lang=en").json()["sections"]["how_it_works"]["title"] == "How it works")
    check("admin sans token -> 401", client.get("/api/v1/home/admin/config").status_code == 401)


    print("Affiches du hero (images) + titre anime + encart paiement")
    hs = home["sections"]["hero_slides"]
    check("aucune affiche par defaut (elles se publient depuis l'admin)", hs["data"]["slides"] == [], str(hs["data"]))
    check("reglages par defaut : ratio / ajustement / style / lecture auto", hs["payload"]["ratio"] == "4/3" and hs["payload"]["fit"] == "cover" and hs["payload"]["transition"] == "stack" and hs["payload"]["autoplay"] is True and hs["payload"]["show_caption"] is False)
    check("plus de carte prestataire de secours", "preview" not in home["sections"]["hero"]["payload"])
    tw = home["sections"]["hero"]["payload"]["typewriter"]
    check("titre anime configurable (machine a ecrire)", tw["enabled"] is True and tw["loop"] is True and tw["speed_ms"] > 0, str(tw))
    cfg = client.get("/api/v1/home/admin/config", headers=H).json()
    sl = next(x for x in cfg if x["key"] == "hero_slides")
    check("aucune carte copiee dans l'admin", sl["items"] == [])
    r = client.post("/api/v1/home/admin/items", headers=H, json={"section_key": "hero_slides", "kind": "poster", "title": "Affiche A", "title_en": "Poster A", "subtitle": "Sous-titre", "image_url": "https://example.test/a.jpg",
                    "link_url": "/recherche?q=plomberie", "data": {"image_mobile": "https://example.test/a-m.jpg", "cta_label": "Decouvrir", "cta_label_en": "Discover"}})
    check("publier une affiche (image + mobile + lien + bouton)", r.status_code == 201, r.text[:150])
    client.post("/api/v1/home/admin/items", headers=H, json={"section_key": "hero_slides", "kind": "poster", "title": "Affiche B", "image_url": "https://example.test/b.jpg"})
    client.post("/api/v1/home/admin/items", headers=H, json={"section_key": "hero_slides", "kind": "poster", "title": "Sans image", "image_url": None})
    sl_fr = client.get("/api/v1/home?lang=fr").json()["sections"]["hero_slides"]["data"]["slides"]
    check("2 affiches (l'item sans image est ignore), dans l'ordre", [x["title"] for x in sl_fr] == ["Affiche A", "Affiche B"], str(sl_fr))
    a_fr = sl_fr[0]
    check("affiche : image, version mobile, lien, bouton", a_fr["image_url"] == "https://example.test/a.jpg" and a_fr["image_url_mobile"] == "https://example.test/a-m.jpg" and a_fr["cta_label"] == "Decouvrir" and a_fr["link_url"] == "/recherche?q=plomberie", str(a_fr))
    a_en = client.get("/api/v1/home?lang=en").json()["sections"]["hero_slides"]["data"]["slides"][0]
    check("version anglaise (titre + bouton)", a_en["title"] == "Poster A" and a_en["cta_label"] == "Discover")
    check("ids uniques", len({x["id"] for x in sl_fr}) == 2)
    # fenetre de diffusion : une affiche expiree disparait, une affiche future aussi
    items = client.get("/api/v1/home/admin/config", headers=H).json()
    sl_items = next(x for x in items if x["key"] == "hero_slides")["items"]
    b_item = next(i for i in sl_items if i["title"] == "Affiche B")
    body_b = {k: b_item[k] for k in b_item if k not in ("id", "section_key")}
    body_b["ends_at"] = "2000-01-01T00:00:00"
    check("PUT affiche (fin de diffusion passee)", client.put(f"/api/v1/home/admin/items/{b_item['id']}", headers=H, json=body_b).status_code == 200)
    check("affiche expiree masquee", [x["title"] for x in client.get("/api/v1/home?lang=fr").json()["sections"]["hero_slides"]["data"]["slides"]] == ["Affiche A"])
    body_b["ends_at"], body_b["starts_at"] = None, "2999-01-01T00:00:00"
    client.put(f"/api/v1/home/admin/items/{b_item['id']}", headers=H, json=body_b)
    check("affiche programmee dans le futur masquee", len(client.get("/api/v1/home?lang=fr").json()["sections"]["hero_slides"]["data"]["slides"]) == 1)
    body_b["starts_at"], body_b["is_active"] = None, False
    client.put(f"/api/v1/home/admin/items/{b_item['id']}", headers=H, json=body_b)
    check("affiche desactivee masquee", len(client.get("/api/v1/home?lang=fr").json()["sections"]["hero_slides"]["data"]["slides"]) == 1)
    sl["payload"].update({"transition": "coverflow", "interval_ms": 3000, "show_dots": False, "ratio": "16/9", "fit": "contain", "show_caption": True})
    r = client.put("/api/v1/home/admin/sections/hero_slides", headers=H, json={k: sl[k] for k in ("title", "title_en", "subtitle", "subtitle_en", "payload", "payload_en", "is_active", "sort_order")})
    check("PUT reglages des affiches", r.status_code == 200, r.text[:150])
    hp = client.get("/api/v1/home?lang=fr").json()["sections"]["hero_slides"]["payload"]
    check("style / duree / ratio / ajustement / legende / points modifies", hp["transition"] == "coverflow" and hp["interval_ms"] == 3000 and hp["ratio"] == "16/9" and hp["fit"] == "contain" and hp["show_caption"] is True and hp["show_dots"] is False, str(hp))
    r = client.post("/api/v1/home/admin/upload-image", headers=H, files={"file": ("x.txt", b"pas une image", "text/plain")})
    check("upload : un fichier non image est refuse", r.status_code == 400, r.text[:120])
    check("upload : protege (401 sans jeton)", client.post("/api/v1/home/admin/upload-image", files={"file": ("x.png", b"x", "image/png")}).status_code == 401)
    hero_cfg = next(x for x in cfg if x["key"] == "hero")
    hero_cfg["payload"]["pay_note"] = {"kicker": "Paiement 100 % protege", "text": "Votre argent reste bloque jusqu'a la fin."}
    hero_cfg["payload"]["typewriter"]["speed_ms"] = 120
    hero_cfg["payload_en"]["pay_note"] = {"text": "Your money stays held until the work is done."}
    r = client.put("/api/v1/home/admin/sections/hero", headers=H, json={k: hero_cfg[k] for k in ("title", "title_en", "subtitle", "subtitle_en", "payload", "payload_en", "is_active", "sort_order")})
    check("PUT hero (encart + vitesse d'ecriture)", r.status_code == 200, r.text[:150])
    fr_h = client.get("/api/v1/home?lang=fr").json()["sections"]["hero"]["payload"]
    en_h = client.get("/api/v1/home?lang=en").json()["sections"]["hero"]["payload"]
    check("encart paiement modifiable (FR)", fr_h["pay_note"]["text"] == "Votre argent reste bloque jusqu'a la fin." and fr_h["typewriter"]["speed_ms"] == 120)
    check("encart paiement : EN partiel, le titre retombe sur le francais", en_h["pay_note"]["text"] == "Your money stays held until the work is done." and en_h["pay_note"]["kicker"] == "Paiement 100 % protege", str(en_h["pay_note"]))
    cleanup_sql.append(("DELETE FROM academy_home_items WHERE section_key='hero_slides'", {}))
    cleanup_sql.append(("DELETE FROM academy_content_sections WHERE `key` IN ('hero_slides')", {}))
    cleanup_sql.append(("DELETE FROM academy_content_sections WHERE `key` IN ('hero')", {}))

    print("Admin : sections")
    cfg = client.get("/api/v1/home/admin/config", headers=H)
    check("GET admin/config", cfg.status_code == 200 and len(cfg.json()) == 15)
    sec = next(s for s in cfg.json() if s["key"] == "hero")
    sec["payload"]["badge"] = "Badge modifie par le test"
    sec["title"] = "Titre modifie"
    r = client.put("/api/v1/home/admin/sections/hero", headers=H, json={k: sec[k] for k in ("title", "title_en", "subtitle", "subtitle_en", "payload", "payload_en", "is_active", "sort_order")})
    check("PUT section hero", r.status_code == 200, r.text)
    hero = client.get("/api/v1/home?lang=fr").json()["sections"]["hero"]
    check("modification visible dans /home (cache invalide)", hero["title"] == "Titre modifie" and hero["payload"]["badge"] == "Badge modifie par le test")
    cleanup_sql.append(("DELETE FROM academy_content_sections WHERE `key`='hero'", {}))
    r = client.put("/api/v1/home/admin/sections/inconnue", headers=H, json={})
    check("section inconnue -> 404", r.status_code == 404)

    print("Admin : desactiver / reordonner une section")
    r = client.put("/api/v1/home/admin/sections/news", headers=H, json={"title": "", "payload": {}, "payload_en": {}, "is_active": False, "sort_order": 0})
    check("desactiver news", r.status_code == 200)
    check("news absente de /home", "news" not in client.get("/api/v1/home?lang=fr").json()["sections"])
    cleanup_sql.append(("DELETE FROM academy_content_sections WHERE `key`='news'", {}))

    print("Admin : cartes")
    r = client.post("/api/v1/home/admin/items", headers=H, json={"section_key": "popular_searches", "kind": "chip", "title": "Puce de test", "title_en": "Test chip"})
    check("POST item (defauts conserves)", r.status_code == 201, r.text)
    item_id = r.json()["id"]
    chips = client.get("/api/v1/home?lang=fr").json()["sections"]["popular_searches"]["items"]
    check("defauts copies + nouvelle puce ajoutee en derniere position (6)", len(chips) == 6 and chips[-1]["title"] == "Puce de test", str([c["title"] for c in chips]))
    r = client.put(f"/api/v1/home/admin/items/{item_id}", headers=H, json={"kind": "chip", "title": "Puce modifiee", "sort_order": 5})
    check("PUT item", r.status_code == 200)
    second = client.get("/api/v1/home?lang=fr").json()["sections"]["popular_searches"]["items"][1]
    check("tri par sort_order (5 -> en 2e position)", second["title"] == "Puce modifiee")
    all_ids = [i["id"] for i in client.get("/api/v1/home/admin/config", headers=H).json()[next(n for n, s in enumerate(client.get("/api/v1/home/admin/config", headers=H).json()) if s["key"] == "popular_searches")]["items"]]
    r = client.post("/api/v1/home/admin/sections/popular_searches/reorder", headers=H, json={"ids": list(reversed(all_ids))})
    check("reorder", r.status_code == 200)
    r = client.delete(f"/api/v1/home/admin/items/{item_id}", headers=H)
    check("DELETE item", r.status_code == 204)
    cleanup_sql.append(("DELETE FROM academy_home_items WHERE section_key='popular_searches'", {}))

    print("Admin : service lie au catalogue")
    sub = client.get("/api/v1/home/admin/catalog/sub-categories", headers=H).json()
    check("catalogue sous-categories", len(sub) > 0)
    r = client.post("/api/v1/home/admin/items", headers=H, json={"section_key": "services", "kind": "service", "ref_type": "sub_category", "ref_id": sub[0]["id"], "tone": "gold"})
    check("POST service reference", r.status_code == 201, r.text)
    svc = client.get("/api/v1/home?lang=fr").json()["sections"]["services"]["items"]
    check("nom lu depuis sub_categories", len(svc) == 1 and svc[0]["title"] == sub[0]["name"], str(svc))
    cleanup_sql.append(("DELETE FROM academy_home_items WHERE section_key='services'", {}))

    print("Admin : prestataire mis en avant")
    prov = client.get("/api/v1/providers/admin?only_certified=true", headers=H).json()
    check("liste prestataires", len(prov) > 0)
    current_tops = client.get("/api/v1/home?lang=fr").json()["sections"]["top_providers"]["data"]["providers"]
    target = current_tops[-1]["vendor_id"]  # le dernier du classement actuel : doit passer en tete
    r = client.put(f"/api/v1/providers/admin/{target}/profile", headers=H, json={"is_featured": True, "featured_order": 1, "is_insured": True, "top_override": 1, "response_time_minutes": 15, "on_time_rate": 98})
    check("PUT profil prestataire", r.status_code == 200, r.text)
    tops = client.get("/api/v1/home?lang=fr").json()["sections"]["top_providers"]["data"]["providers"]
    check("prestataire mis en avant en tete", tops[0]["vendor_id"] == target and tops[0]["badges"]["insured"] and tops[0]["badges"]["top"], str(tops[0]))
    cleanup_sql.append(("DELETE FROM academy_provider_profiles WHERE vendor_id=:v", {"v": target}))
    r = client.put(f"/api/v1/providers/admin/{target}/availability", headers=H, json=[{"weekday": 0, "start_time": "08:00:00", "end_time": "17:00:00"}])
    check("PUT disponibilites", r.status_code == 200, r.text)
    r = client.put(f"/api/v1/providers/admin/{target}/availability", headers=H, json=[{"weekday": 0, "start_time": "10:00:00", "end_time": "09:00:00"}])
    check("plage invalide -> 400", r.status_code == 400)
    cleanup_sql.append(("DELETE FROM academy_provider_availability WHERE vendor_id=:v", {"v": target}))
    r = client.post(f"/api/v1/providers/admin/{target}/media", headers=H, json={"kind": "photo", "url": "https://example.test/a.jpg"})
    check("POST media", r.status_code == 201, r.text)
    cleanup_sql.append(("DELETE FROM academy_provider_media WHERE vendor_id=:v", {"v": target}))

    print("Admin : avis")
    r = client.post("/api/v1/reviews/admin/import-booking-marks", headers=H)
    check("import booking_marks", r.status_code == 200 and r.json()["imported"] > 0, r.text)
    first_import = r.json()
    r = client.post("/api/v1/reviews/admin/import-booking-marks", headers=H)
    check("import idempotent (0 doublon)", r.json()["imported"] == 0 and r.json()["skipped_existing"] == first_import["imported"], r.text)
    pend = client.get("/api/v1/reviews/admin?status=pending", headers=H).json()
    check("avis importes en 'pending'", len(pend) == first_import["imported"])
    pub_before = len(client.get("/api/v1/home?lang=fr").json()["sections"]["testimonials"]["data"]["reviews"])
    r = client.patch(f"/api/v1/reviews/admin/{pend[0]['id']}", headers=H, json={"status": "approved", "reply": "Merci !"})
    check("approuver + repondre", r.status_code == 200 and r.json()["status"] == "approved" and r.json()["reply"] == "Merci !", r.text)
    cleanup_sql.append(("DELETE FROM academy_reviews WHERE source='booking_mark'", {}))
finally:
    # la session ouverte au debut peut avoir expire (base distante) : nettoyage avec une session neuve
    try:
        db.close()
    except Exception:  # connexion expiree cote serveur : on repart d'une session neuve
        pass
    db = SessionLocal()
    for t in saved_trust:
        db.execute(text("UPDATE academy_trust_scores SET score_pct=:a, rules_score=:b, rules_breakdown_json=:c, llm_score=:d, justification=:e, computed_at=:f WHERE id=:i"),
                   {"i": t[0], "a": t[1], "b": t[2], "c": t[3], "d": t[4], "e": t[5], "f": t[6]})
    for sql, params in reversed(cleanup_sql):
        db.execute(text(sql), params)
    db.commit()
    for table, rows in (("academy_content_sections", saved_home_sections), ("academy_home_items", saved_home_items)):
        for row in rows:
            cols = ", ".join(f"`{k}`" for k in row)
            db.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({', '.join(':' + k for k in row)})"), row)
    db.commit()
    from app.services.home import invalidate_home_cache

    invalidate_home_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
