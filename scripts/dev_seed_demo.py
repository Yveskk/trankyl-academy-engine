"""Donnees de DEMONSTRATION pour la recherche et les profils : prestataires
fictifs avec certificats, services et prix, disponibilites, realisations,
avis notes, reservations. Uniquement pour la base dev (`*_dev_db`, refuse
sinon). Strictement additif et idempotent : n'ecrase ni ne supprime rien,
et s'arrete si les donnees de demo existent deja. Aucune donnee reelle.

Usage : python -m scripts.dev_seed_demo
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

from sqlalchemy import create_engine, text  # noqa: E402

url = os.environ["DATABASE_URL"]
db_name = url.rsplit("/", 1)[-1].split("?")[0]
if not db_name.endswith("_dev_db"):
    sys.exit(f"Refus : '{db_name}' n'est pas une base dev.")
engine = create_engine(url)
rnd = random.Random(2026)
NOW = datetime(2026, 10, 1, 9, 0, 0)

# ----------------------------------------------------------------------------
# Referentiel de metiers (sous-categorie du catalogue + metier Academy de meme id)
# ----------------------------------------------------------------------------
METIERS = {  # cle: (nom FR, nom EN, categorie)
    "plomberie": ("Plomberie", "Plumbing", "Reparation Installation"),
    "electricite": ("Electricite", "Electricity", "Reparation Installation"),
    "nettoyage": ("Nettoyage maison", "House cleaning", "Nettoyage"),
    "garde": ("Garde d'enfants", "Childcare", "Aide a domicile"),
    "cuisine": ("Cuisine & traiteur", "Catering", "Aide a domicile"),
    "clim": ("Climatisation", "Air conditioning", "Reparation Installation"),
    "menuiserie": ("Menuiserie", "Carpentry", "Reparation Installation"),
    "peinture": ("Peinture", "Painting", "Reparation Installation"),
    "coiffure": ("Coiffure & beaute", "Hair & beauty", "Beaute"),
    "chauffeur": ("Chauffeur", "Driver", "Logistique transport"),
    "couture": ("Couture", "Tailoring", "A porter"),
    "aide": ("Aide a domicile", "Home help", "Aide a domicile"),
}

SERVICES = {  # cle: [(titre, description, prix FCFA ou None)]
    "plomberie": [("Reparation de fuite / robinet", "Diagnostic + main d'oeuvre", 8000), ("Debouchage evier / WC", "Furet manuel ou electrique", 10000), ("Installation chauffe-eau", "Hors fourniture", 25000), ("Installation sanitaire complete", "Sur devis apres visite", None), ("Contrat d'entretien mensuel", "Immeubles, restaurants", None)],
    "electricite": [("Depannage electrique", "Panne, disjoncteur, prise", 6000), ("Installation de prises et eclairage", "Main d'oeuvre", 12000), ("Mise aux normes tableau", "Sur devis apres visite", None)],
    "nettoyage": [("Menage a domicile", "Forfait 4 heures", 7500), ("Menage de fin de chantier", "Sur devis apres visite", None), ("Nettoyage de vitres", "Par vitre", 1500)],
    "garde": [("Garde d'enfants a la journee", "Journee de 8 heures", 9000), ("Garde du soir", "Apres l'ecole, jusqu'a 20h", 6000), ("Sortie d'ecole", "Aller-retour", 3000)],
    "cuisine": [("Repas pour evenement", "Jusqu'a 30 personnes", 45000), ("Cuisinier a domicile", "Repas du jour", 12000), ("Buffet traiteur", "Sur devis", None)],
    "clim": [("Entretien climatiseur", "Nettoyage + controle", 9000), ("Recharge de gaz", "Selon modele", 18000), ("Installation split", "Hors fourniture", 30000)],
    "menuiserie": [("Reparation de porte / fenetre", "Main d'oeuvre", 7000), ("Meuble sur mesure", "Sur devis apres visite", None), ("Pose d'armoire", "Par element", 15000)],
    "peinture": [("Peinture d'une piece", "Main d'oeuvre", 25000), ("Peinture exterieure", "Sur devis", None), ("Retouches", "Forfait journee", 8000)],
    "coiffure": [("Tresses a domicile", "Selon modele", 8000), ("Coiffure de mariage", "Essai inclus", 35000), ("Soins et brushing", "A domicile", 6000)],
    "chauffeur": [("Chauffeur a la journee", "8 heures", 15000), ("Trajet aeroport", "Aller simple", 6000), ("Livraison express", "Dans l'agglomeration", 2500)],
    "couture": [("Retouches", "Ourlet, taille", 2000), ("Robe sur mesure", "Tissu fourni par le client", 20000), ("Tenue complete", "Sur devis", None)],
    "aide": [("Aide a la personne agee", "Demi-journee", 6000), ("Accompagnement courses", "2 heures", 3500), ("Presence de nuit", "Sur devis", None)],
}

QUOTES = {
    "plomberie": ["Rapide, propre, et il a explique la panne avant de commencer.", "Prix annonce respecte, facture recue sur WhatsApp.", "Ponctuel, a laisse la cuisine impeccable.", "Tres bon contact, je le rappellerai.", "Il a montre la piece usee et le prix de la nouvelle avant de la changer."],
    "electricite": ["Panne reparee en moins d'une heure, travail soigne.", "Explications claires et tarif honnete.", "Arrive a l'heure, tout fonctionne depuis."],
    "nettoyage": ["Maison impeccable, equipe tres serieuse.", "Ponctuelle et discrete, je recommande.", "Excellent travail, produits fournis."],
    "garde": ["Mes enfants l'adorent, tres rassurante.", "Ponctuelle, attentive et patiente.", "Une nounou de confiance, certificat a l'appui."],
    "cuisine": ["Repas delicieux pour notre mariage, service parfait.", "Cuisine savoureuse et propre.", "Tres professionnel, les invites ont adore."],
    "clim": ["Climatiseur comme neuf apres l'entretien.", "Diagnostic honnete, pas de pieces inutiles.", "Intervention rapide en pleine chaleur."],
    "menuiserie": ["Porte parfaitement reglee, finition impeccable.", "Meuble sur mesure exactement comme prevu.", "Soigneux et ponctuel."],
    "peinture": ["Murs impeccables, sol protege.", "Travail propre et rapide.", "Belle finition, prix respecte."],
    "coiffure": ["Tresses magnifiques et tenue parfaite.", "Venue a domicile, tres pratique.", "Coiffure de mariage reussie."],
    "chauffeur": ["Conduite prudente et ponctuel.", "Arrive toujours a l'heure, voiture propre.", "Tres professionnel."],
    "couture": ["Robe parfaitement ajustee.", "Retouches impeccables, livraison a temps.", "Tres belle finition."],
    "aide": ["Attentionne avec ma mere, merci.", "Personne de confiance et patiente.", "Tres a l'ecoute."],
}

# (nom, metier, ville, quartiers, lat, lng, note, nb_missions, nb_avis, langues, annees, reponse_min, assure, ponctualite, frais_visite, dispo, vedette)
QUARTIERS = {"Be": (6.1375, 1.2230), "Tokoin": (6.1456, 1.2186), "Adidogome": (6.1750, 1.1950), "Agoe": (6.2290, 1.2150), "Hedzranawoe": (6.1700, 1.2350), "Nyekonakpoe": (6.1300, 1.2200), "Kodjoviakope": (6.1260, 1.2060), "Djidjole": (6.1620, 1.2150)}
DEMO = [
    ("Komlan Agbeko", "plomberie", ["Be", "Tokoin"], 4.8, 154, 71, "Francais, Ewe, Mina", 10, 20, True, 97, 5000, "full", False),
    ("Yawo Semenou", "plomberie", ["Adidogome", "Agoe"], 4.6, 63, 28, "Francais, Ewe", 6, 40, False, 92, 4000, "weekdays", False),
    ("Edoh Kpogo", "plomberie", ["Nyekonakpoe", "Kodjoviakope"], 4.9, 301, 133, "Francais, Mina", 15, 10, True, 99, 6000, "full", True),
    ("Kodjo Amegah", "electricite", ["Be", "Hedzranawoe"], 4.9, 175, 88, "Francais, Ewe", 12, 15, True, 98, 5000, "full", False),
    ("Selom Dogbe", "electricite", ["Tokoin", "Djidjole"], 4.5, 49, 20, "Francais", 5, 55, False, 90, 3500, "weekdays", False),
    ("Mawuena Kpade", "electricite", ["Agoe", "Adidogome"], 4.7, 96, 41, "Francais, Ewe, Kabiye", 8, 30, True, 95, 4500, "full", False),
    ("Akossiwa Tsogbe", "nettoyage", ["Be", "Nyekonakpoe"], 4.9, 260, 120, "Francais, Ewe", 9, 25, True, 99, 0, "full", False),
    ("Dede Amouzou", "nettoyage", ["Tokoin", "Kodjoviakope"], 4.7, 88, 36, "Francais, Mina", 4, 45, False, 94, 0, "weekdays", False),
    ("Ablavi Koffi", "nettoyage", ["Agoe", "Hedzranawoe"], 4.6, 54, 22, "Francais, Ewe", 3, 70, False, 91, 0, "weekend", False),
    ("Adjo Lawson", "garde", ["Be", "Tokoin"], 4.9, 190, 83, "Francais, Ewe, Anglais", 11, 12, True, 99, 0, "full", True),
    ("Kafui Mensah", "garde", ["Djidjole", "Agoe"], 4.8, 120, 52, "Francais, Mina", 7, 35, True, 97, 0, "weekdays", False),
    ("Enyonam Dzidzo", "garde", ["Adidogome", "Be"], 4.5, 41, 18, "Francais, Ewe", 3, 60, False, 90, 0, "full", False),
    ("Delali Apedo", "cuisine", ["Tokoin", "Be"], 4.8, 140, 64, "Francais, Ewe", 14, 20, True, 96, 15000, "full", False),
    ("Sitsope Fiawoo", "cuisine", ["Hedzranawoe", "Agoe"], 4.6, 72, 30, "Francais, Mina", 6, 50, False, 93, 10000, "weekend", False),
    ("Koffi Ahiable", "clim", ["Be", "Nyekonakpoe"], 4.9, 210, 97, "Francais, Ewe", 13, 15, True, 98, 5000, "full", False),
    ("Yao Tchalla", "clim", ["Tokoin", "Djidjole"], 4.6, 66, 27, "Francais", 6, 40, True, 92, 4000, "weekdays", False),
    ("Atsu Gbedemah", "menuiserie", ["Agoe", "Adidogome"], 4.7, 92, 40, "Francais, Ewe", 16, 30, False, 95, 6000, "weekdays", False),
    ("Nana Houndete", "menuiserie", ["Be", "Kodjoviakope"], 4.8, 118, 50, "Francais, Mina", 18, 25, True, 96, 6500, "full", False),
    ("Kossi Agbenyega", "peinture", ["Tokoin", "Hedzranawoe"], 4.7, 105, 44, "Francais, Ewe", 9, 35, False, 94, 5000, "full", False),
    ("Ameyo Adjei", "coiffure", ["Be", "Djidjole"], 4.9, 230, 101, "Francais, Ewe, Mina", 8, 10, False, 99, 2000, "full", False),
    ("Koku Dodzi", "chauffeur", ["Tokoin", "Be"], 4.8, 310, 140, "Francais, Ewe, Anglais", 10, 10, False, 98, 0, "full", False),
    ("Mawusi Quashie", "couture", ["Adidogome", "Agoe"], 4.8, 150, 66, "Francais, Ewe", 12, 25, False, 97, 3000, "weekdays", False),
    ("Abla Sodji", "aide", ["Be", "Nyekonakpoe"], 4.9, 98, 45, "Francais, Ewe", 7, 20, True, 98, 0, "full", False),
    ("Fiona Gbadamassi", "garde", ["Kodjoviakope", "Tokoin"], 4.7, 0, 0, "Francais, Anglais", 2, 90, False, 0, 0, "none", False),
]
FIRST_COMMENT_CLIENTS = ["Ama", "Jean-Paul", "Afi", "Komi", "Sena", "Yawovi", "Mawuli", "Dela", "Ines", "Eli"]


def ins(conn, table: str, **cols) -> int:
    names = ", ".join(f"`{c}`" for c in cols)
    params = ", ".join(f":{c}" for c in cols)
    return conn.execute(text(f"INSERT INTO `{table}` ({names}) VALUES ({params})"), cols).lastrowid


def many(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    names = ", ".join(f"`{c}`" for c in rows[0])
    params = ", ".join(f":{c}" for c in rows[0])
    conn.execute(text(f"INSERT INTO `{table}` ({names}) VALUES ({params})"), rows)


with engine.begin() as conn:
    if conn.execute(text("SELECT COUNT(*) FROM vendors WHERE vendor_email LIKE 'demo%@seed.example.test'")).scalar():
        sys.exit("Donnees de demo deja presentes : rien fait.")

    # --- categories / sous-categories / metiers (additif : on reutilise l'existant) ----
    cat_ids: dict[str, int] = {}
    for fr_cat in {m[2] for m in METIERS.values()}:
        row = conn.execute(text("SELECT cat_id FROM categories WHERE cat_name_fr=:n"), {"n": fr_cat}).first()
        cat_ids[fr_cat] = row[0] if row else ins(conn, "categories", cat_name_fr=fr_cat, cat_name_en=fr_cat, cat_desp_fr="-", cat_desp_en="-", cat_image="uploads/category/demo.png", cat_order=50, cat_is_active=1)
    sub_ids: dict[str, int] = {}
    for key, (fr, en, cat) in METIERS.items():
        row = conn.execute(text("SELECT subcat_id FROM sub_categories WHERE subcat_name_fr=:n"), {"n": fr}).first()
        sub_ids[key] = row[0] if row else ins(conn, "sub_categories", subcat_name_fr=fr, subcat_name_en=en, subcat_desp_fr=f"Service de {fr.lower()}", subcat_desp_en=f"{en} service", subcat_image=f"uploads/subcategory/demo_{key}.jpeg", subcat_cat_id=cat_ids[cat], subcat_is_active=1)
    niveau_ids: dict[tuple[str, int], int] = {}
    for key, (fr, en, _cat) in METIERS.items():
        sid = sub_ids[key]
        if not conn.execute(text("SELECT 1 FROM academy_metiers WHERE id=:i"), {"i": sid}).first():
            ins(conn, "academy_metiers", id=sid, code=key, nom=fr, description=f"Parcours {fr}", nom_en=en, description_en=f"{en} path", is_active=1)
        for num in (1, 2):
            row = conn.execute(text("SELECT id FROM academy_niveaux WHERE metier_id=:m AND numero=:n"), {"m": sid, "n": num}).first()
            niveau_ids[(key, num)] = row[0] if row else ins(conn, "academy_niveaux", metier_id=sid, numero=num, nom=f"{fr} - niveau {num}", description="demo", nom_en=f"{en} - level {num}", description_en="demo")

    # --- clients de demo (auteurs d'avis) ---------------------------------------
    clients = [ins(conn, "clients", client_unique_id=f"DEMOC{i:03d}", client_name=f"{n} Demo", client_email=f"democlient{i}@seed.example.test", client_phone=f"+2289200{i:04d}", client_is_active=1) for i, n in enumerate(FIRST_COMMENT_CLIENTS, 1)]

    # --- prestataires de demo -------------------------------------------------------
    booking_rows: list[dict] = []
    mark_targets: list[tuple[int, int, int]] = []  # (index booking, note, vendor)
    for idx, (name, key, quartiers, mark, missions, n_reviews, langs, years, resp, insured, ontime, fee, dispo, featured) in enumerate(DEMO, 1):
        lat0, lng0 = QUARTIERS[quartiers[0]]
        vid = ins(conn, "vendors", vendor_unique_id=f"DEMO{idx:04d}", vendor_name=name, vendor_email=f"demo{idx}@seed.example.test", vendor_phone=f"+2289300{idx:04d}",
                  vendor_bio=f"{name}, {METIERS[key][0].lower()} a Lome. Prestataire fictif de demonstration.", vendor_address_city="Lome", vendor_country_id=217, vendor_city_id=1,
                  vendor_working_district=", ".join(quartiers), vendor_local_languages=langs, vendor_is_active=1, vendor_mark=mark or None, vendor_jobs_count=missions,
                  vendor_sign_up_at=NOW - timedelta(days=365 * (years // 3 + 1) - rnd.randint(0, 200)), vendor_created_at=NOW - timedelta(days=400),
                  vendor_latitude=round(lat0 + rnd.uniform(-0.004, 0.004), 6), vendor_longitude=round(lng0 + rnd.uniform(-0.004, 0.004), 6),
                  vendor_academy_status="certified_provider", vendor_academy_verified=1, vendor_academy_verified_at=NOW)
        ins(conn, "academy_trust_scores", vendor_id=vid, score_pct=round(rnd.uniform(62, 94), 1), rules_score=70, rules_breakdown_json="{}", justification="demo", computed_at=NOW)
        for num in (1, 2) if missions > 80 else (1,):
            ins(conn, "academy_certifications", vendor_id=vid, niveau_id=niveau_ids[(key, num)], code=f"{key}_niveau_{num}", taxonomy_version=1, delivree_at=NOW - timedelta(days=rnd.randint(60, 700)))
        many(conn, "services", [dict(s_subcat_id=str(sub_ids[key]), s_district_id="1", s_vendor_id=str(vid), s_tools_used="-", s_title=t, s_desp=d, s_exp=str(years), s_sub_services="-", s_min_price=p or 0, s_is_active="1", s_options="-", s_country_id="217", s_city_id="1", s_created_at=NOW) for t, d, p in SERVICES[key]])

        # profil enrichi
        slug = None
        ins(conn, "academy_provider_profiles", vendor_id=vid, headline=f"{METIERS[key][0]} a Lome", about=f"{years} ans d'experience. Je me deplace avec mon materiel, j'explique avant d'intervenir et je laisse les lieux propres. Je parle {langs.replace(',', ',').lower()}.",
            cover_image_url="https://images.unsplash.com/photo-1504159506876-f8338247a14a?auto=format&fit=crop&w=1600&q=80", response_time_minutes=resp or None, on_time_rate=ontime or None,
            is_insured=1 if insured else 0, is_address_verified=1, is_featured=1 if featured else 0, featured_order=idx if featured else 0, public_slug=slug,
            visit_fee=fee or None, years_experience=years, service_radius_km=8, zone_label=f"Rayon 8 km autour de {quartiers[0]}",
            services_note="Prix final confirme dans le devis, apres diagnostic. Pieces facturees a part avec justificatif.", services_note_en="Final price confirmed in the quote after diagnosis. Parts billed separately with receipt.")

        # realisations
        photos = ["https://images.unsplash.com/photo-1504159506876-f8338247a14a", "https://images.unsplash.com/photo-1516627145497-ae6968895b74", "https://images.unsplash.com/photo-1542810634-71277d95dcbb"]
        many(conn, "academy_provider_media", [dict(vendor_id=vid, kind="before_after" if i == 0 else "photo", url=f"{u}?auto=format&fit=crop&w=800&q=80", caption=f"Realisation {i + 1}", sort_order=i * 10, is_active=1, created_at=NOW) for i, u in enumerate(photos)])

        # disponibilites hebdomadaires (0 = lundi)
        plan = {"full": range(0, 6), "weekdays": range(0, 5), "weekend": (5, 6), "none": ()}[dispo]
        many(conn, "academy_provider_availability", [dict(vendor_id=vid, weekday=d, start_time="08:00:00", end_time="18:00:00" if d < 5 else "14:00:00", is_active=1, created_at=NOW) for d in plan])

        # reservations (donnent le nombre de missions) + avis approuves
        n_book = min(missions, 25)
        for b in range(n_book):
            booking_rows.append(dict(bk_unique_id=f"DEMOBK{idx:03d}{b:03d}", bk_client_id=clients[b % len(clients)], bk_vendor_id=vid, bk_selected_time="14:00", bk_total_amount="8000", bk_amount_paid="8000", bk_time="14:00", bk_address="Lome", bk_payment_method="mobile_money", bk_qty="1", bk_service_status="2", bk_date=(NOW - timedelta(days=rnd.randint(2, 300))).date(), bk_created_at=NOW))
        comments = QUOTES[key]
        for r in range(min(n_reviews, 7)):
            rating = 5 if rnd.random() < max(0.0, (mark - 4.0)) else 4
            crit = {k: max(1, min(5, rating + rnd.choice([0, 0, 0, -1] if rating == 5 else [0, 0, 1]))) for k in ("punctuality", "quality", "cleanliness", "price")}
            ins(conn, "academy_reviews", vendor_id=vid, client_id=clients[(idx + r) % len(clients)], rating=rating, comment=comments[r % len(comments)], created_at=NOW - timedelta(days=3 + r * 11 + rnd.randint(0, 5)), status="approved", source="academy",
                criteria_json=json.dumps(crit), reply=("Merci pour votre confiance !" if r % 3 == 0 else None), replied_at=(NOW if r % 3 == 0 else None))

    many(conn, "bookings", booking_rows)

    # --- enrichir les 6 premiers prestataires du jeu v1 (Kossi, Mawuli, ...) --------
    for i in range(1, 7):
        row = conn.execute(text("SELECT vendor_id FROM vendors WHERE vendor_email=:e"), {"e": f"seed{i}@seed.example.test"}).first()
        if not row:
            continue
        vid = row[0]
        if conn.execute(text("SELECT 1 FROM academy_provider_profiles WHERE vendor_id=:v"), {"v": vid}).first():
            continue
        key = ["plomberie", "plomberie", "electricite", "garde", "garde", "nettoyage"][i - 1]
        ins(conn, "academy_provider_profiles", vendor_id=vid, headline=f"{METIERS[key][0]} a Lome", about="12 ans d'experience en plomberie sanitaire et reseaux d'eau. Je me deplace avec mon materiel, j'explique la panne avant d'intervenir et je laisse les lieux propres. Je parle francais, ewe et mina." if i == 1 else "Prestataire fictif de demonstration.",
            cover_image_url="https://images.unsplash.com/photo-1504159506876-f8338247a14a?auto=format&fit=crop&w=1600&q=80", response_time_minutes=[15, 30, 20, 45, 25, 35][i - 1], on_time_rate=[98, 96, 97, 94, 95, 96][i - 1], is_insured=1 if i != 3 else 0,
            is_address_verified=1, public_slug=("kossi-plombier" if i == 1 else None), visit_fee=5000 if i == 1 else 4000, years_experience=12, service_radius_km=8, zone_label="Rayon 8 km autour de Be",
            services_note="Prix final confirme dans le devis, apres diagnostic. Pieces facturees a part avec justificatif.")
        conn.execute(text("UPDATE vendors SET vendor_working_district=COALESCE(vendor_working_district,'Be, Tokoin, Adidogome'), vendor_local_languages=COALESCE(vendor_local_languages,'Francais, Ewe, Mina') WHERE vendor_id=:v"), {"v": vid})
        many(conn, "academy_provider_availability", [dict(vendor_id=vid, weekday=d, start_time="08:00:00", end_time="18:00:00", is_active=1, created_at=NOW) for d in range(0, 6)])
        many(conn, "academy_provider_media", [dict(vendor_id=vid, kind="photo", url=f"https://images.unsplash.com/photo-1504159506876-f8338247a14a?auto=format&fit=crop&w=800&q=80", caption=f"Realisation {k}", sort_order=k * 10, is_active=1, created_at=NOW) for k in range(1, 5)])
        many(conn, "services", [dict(s_subcat_id=str(sub_ids[key]), s_district_id="1", s_vendor_id=str(vid), s_tools_used="-", s_title=t, s_desp=d, s_exp="12", s_sub_services="-", s_min_price=p or 0, s_is_active="1", s_options="-", s_country_id="217", s_city_id="1", s_created_at=NOW) for t, d, p in SERVICES[key][1:]])
        for r, comment in enumerate(QUOTES[key][:4]):
            ins(conn, "academy_reviews", vendor_id=vid, client_id=clients[(i + r) % len(clients)], rating=5 if r != 2 else 4, comment=comment, created_at=NOW - timedelta(days=3 + r * 12), status="approved", source="academy",
                criteria_json=json.dumps({"punctuality": 5, "quality": 5, "cleanliness": 5 if r % 2 == 0 else 4, "price": 5}), reply=("Merci a vous, a votre service !" if r == 0 else None), replied_at=(NOW if r == 0 else None))

print(f"{len(DEMO)} prestataires de demo, avec certificats, services, disponibilites, realisations, avis et reservations.")
