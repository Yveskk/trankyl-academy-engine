"""Test de la recherche et du profil public sur la base DEV (lecture seule).
Prerequis : python -m scripts.dev_seed_demo. Usage : python -m scripts.dev_search_test"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : base non dev.")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)
fails: list[str] = []


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL"), label, (f"[{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def S(**params):
    r = c.get("/api/v1/directory/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


print("Interpretation du texte libre")
d = S(q="mon robinet de cuisine fuit depuis hier")
i = d["interpretation"]
check("metier detecte = Plomberie", i["label"] == "Plomberie", str(i))
check("urgence = aujourd'hui", i["urgency"] == "today")
check("mots-cles robinet/fuit (mots de la requete)", {"robinet", "fuit"} <= set(i["keywords"]), str(i["keywords"]))
check("budget estime", i["budget"] and i["budget"]["low"] >= 5000 and i["budget"]["high"] > i["budget"]["low"], str(i["budget"]))
check("resultats = uniquement des plombiers", d["total"] >= 4 and all(x["job"] == "Plomberie" for x in d["items"]), str([x["job"] for x in d["items"]]))
check("prix 'des' renseignes", all(x["price_from"] for x in d["items"]))
for q, label in [("nounou pour mes enfants", "Garde d'enfants"), ("panne de courant prise", "Electricite"), ("climatisation entretien", "Climatisation"), ("menage de ma maison", "Nettoyage maison"), ("coiffure mariage tresses", "Coiffure & beaute")]:
    check(f"« {q} » -> {label}", S(q=q)["interpretation"]["label"] == label, str(S(q=q)["interpretation"]["label"]))
check("requete vide : tous les eligibles", S()["total"] >= 20)
check("requete sans sens : liste vide ou generale sans plantage", isinstance(S(q="zzzzqqq")["total"], int))
check("accents / majuscules", S(q="Électricité")["interpretation"]["label"] == "Electricite")

print("Filtres")
base = S(q="plomberie", limit=50)
check("min_rating 4.8", all((x["rating"] or 0) >= 4.8 for x in S(q="plomberie", min_rating=4.8)["items"]) and S(q="plomberie", min_rating=4.8)["total"] < base["total"])
check("insured", all(x["badges"]["insured"] for x in S(q="plomberie", insured=True)["items"]) and S(q="plomberie", insured=True)["total"] < base["total"])
check("top", all(x["badges"]["top"] for x in S(q="plomberie", top=True)["items"]))
check("certified", S(q="plomberie", certified=True)["total"] == base["total"])
kab = S(languages="Kabiye")
check("langue Kabiye", kab["total"] >= 1 and all("Kabiye" in x["languages"] for x in kab["items"]))
check("city inconnue -> 0", S(q="plomberie", city="Atlantide")["total"] == 0)
today, wk = S(q="plomberie", availability="today", limit=50), S(q="plomberie", availability="weekend", limit=50)
# En fin de journee plus aucun creneau "aujourd'hui" : seul le sous-ensemble est verifie.
check("dispo aujourd'hui : un sous-ensemble (+ inconnus)", today["total"] <= base["total"])
check("dispo week-end", wk["total"] > 0)
check("country BJ -> 0 (aucun prestataire au Benin)", S(q="plomberie", country="BJ")["total"] == 0)

print("Tri / pagination / distance")
byrate = S(q="plomberie", sort="rating", limit=50)["items"]
check("tri note decroissante", [x["rating"] or 0 for x in byrate] == sorted([x["rating"] or 0 for x in byrate], reverse=True))
byprice = S(q="plomberie", sort="price", limit=50)["items"]
check("tri prix croissant", [x["price_from"] or 10**9 for x in byprice] == sorted([x["price_from"] or 10**9 for x in byprice]))
d1, d2 = S(q="plomberie", limit=2, offset=0), S(q="plomberie", limit=2, offset=2)
check("pagination sans recouvrement", d1["total"] == d2["total"] and not ({x["vendor_id"] for x in d1["items"]} & {x["vendor_id"] for x in d2["items"]}))
near = S(q="plomberie", district="Be", sort="distance", limit=50)["items"]
dist = [x["distance_km"] for x in near if x["distance_km"] is not None]
check("distances calculees depuis le quartier", len(dist) > 0 and dist == sorted(dist), str(dist[:5]))
gps = S(q="plomberie", lat=6.1375, lng=1.2230, sort="distance")["items"]
check("distance depuis GPS", gps[0]["distance_km"] is not None and gps[0]["distance_km"] < 3)
check("bad sort -> 400", c.get("/api/v1/directory/search", params={"sort": "x"}).status_code == 400)
check("bad availability -> 422", c.get("/api/v1/directory/search", params={"availability": "x"}).status_code == 422)

print("Carte resultat")
x = base["items"][0]
for k in ("vendor_id", "name", "initials", "job", "rating", "reviews_count", "missions", "badges", "price_from", "profile_url", "languages", "lat", "lng", "next_slot"):
    check(f"champ {k}", k in x)
check("nom abrege 'Prenom N.'", x["name"].endswith(".") and len(x["name"].split()) == 2, x["name"])

print("Localites")
loc = c.get("/api/v1/directory/locations?country=TG").json()["locations"]
check("Lome listee", any(l["city"].lower().startswith("lom") for l in loc), str(loc))

print("Profil public")
p = c.get("/api/v1/directory/providers/kossi-plombier").json()
check("par slug public", p.get("name") == "Kossi Amouzou", str(p)[:120])
check("par id", c.get(f"/api/v1/directory/providers/{p['vendor_id']}").json()["vendor_id"] == p["vendor_id"])
check("par texte-id", c.get(f"/api/v1/directory/providers/kossi-{p['vendor_id']}").json()["vendor_id"] == p["vendor_id"])
check("inconnu -> 404", c.get("/api/v1/directory/providers/zzz-999999").status_code == 404)
check("non eligible (non verifie) -> 404", c.get("/api/v1/directory/providers/7").status_code == 404)
check("badges", p["badges"]["identity"] and p["badges"]["address"] and p["badges"]["certified"] and p["badges"]["insured"], str(p["badges"]))
check("stats", p["stats"]["missions"] > 0 and p["stats"]["response_minutes"] == 15 and p["stats"]["on_time_rate"] == 98.0, str(p["stats"]))
check("services avec prix + 'sur devis'", len(p["services"]) >= 4 and any(s["price"] is None for s in p["services"]) and any(s["price"] for s in p["services"]), str(p["services"][:2]))
check("realisations", len(p["media"]) >= 3)
check("formations", len(p["trainings"]) >= 1 and "Plomberie" in p["trainings"][0]["title"], str(p["trainings"]))
check("avis + criteres + reponses", p["reviews"]["count"] >= 4 and len(p["reviews"]["criteria"]) == 4 and any(r["reply"] for r in p["reviews"]["items"]), str(p["reviews"]["criteria"]))
check("creneaux de reservation (4 max)", 1 <= len(p["booking"]["slots"]) <= 4 and p["booking"]["visit_fee"] == 5000, str(p["booking"]))
check("lien de partage", p["share"]["url"].endswith("/profil/kossi-plombier"), p["share"]["url"])
check("zone d'intervention", p["zone"]["lat"] and p["zone"]["radius_km"] == 8)
en = c.get("/api/v1/directory/providers/kossi-plombier?lang=en").json()
check("version anglaise (reponse valide)", en["job"] is not None and en["vendor_id"] == p["vendor_id"], str(en["job"]))
check("avis limites", len(c.get("/api/v1/directory/providers/kossi-plombier?reviews_limit=2").json()["reviews"]["items"]) == 2)
nodata = c.get("/api/v1/directory/providers/" + str(S(q="nounou")["items"][-1]["vendor_id"])).json()
check("prestataire sans dispo : profil OK, slots vides", nodata["booking"]["slots"] == [] or isinstance(nodata["booking"]["slots"], list))

print("Services detailles (page Reserver)")
sv = c.get("/api/v1/directory/providers/kossi-plombier/services").json()
check("liste de services", len(sv["services"]) >= 4, str(sv)[:150])
check("champs service", all(k in sv["services"][0] for k in ("id", "title", "description", "price", "includes", "tools", "options", "experience", "category")))
check("services avec prix et sur devis", any(s["price"] for s in sv["services"]) and any(s["price"] is None for s in sv["services"]))
check("prix minimum", sv["min_price"] == min(s["price"] for s in sv["services"] if s["price"]))
check("frais de deplacement", sv["visit_fee"] == 5000)
check("par id aussi", c.get(f"/api/v1/directory/providers/{sv['vendor_id']}/services").status_code == 200)
check("non eligible -> 404", c.get("/api/v1/directory/providers/7/services").status_code == 404)
check("inconnu -> 404", c.get("/api/v1/directory/providers/zzz-999999/services").status_code == 404)
from app.services.provider_profile import _listify  # noqa: E402
check("_listify JSON liste", _listify('["Diagnostic", "Main d\'oeuvre"]') == ["Diagnostic", "Main d'oeuvre"])
check("_listify JSON objets", _listify('[{"name": "Pose"}, {"title": "Test"}]') == ["Pose", "Test"])
check("_listify texte", _listify("Furet; Clé a molette, Pince (grande, petite)") == ["Furet", "Clé a molette", "Pince (grande, petite)"], str(_listify("Furet; Clé a molette, Pince (grande, petite)")))
check("_listify remplissage ignore", _listify("-") == [] and _listify("") == [] and _listify(None) == [])

print()
print(f"{len(fails)} echec(s) : {fails}" if fails else "Tous les controles passent.")
sys.exit(1 if fails else 0)
