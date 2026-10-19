"""Jeu de donnees FICTIF dans l'etat "v1" (avant les migrations 0002/0003),
uniquement pour la base dev : sert a prouver qu'une migration ne perd rien.
Refuse de tourner hors d'une base `*_dev_db`, et refuse si les prestataires
fictifs existent deja. Aucune donnee reelle."""
import os
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

NOW = datetime(2026, 9, 1, 10, 0, 0)


def ins(conn, table: str, **cols) -> int:
    names = ", ".join(f"`{c}`" for c in cols)
    params = ", ".join(f":{c}" for c in cols)
    return conn.execute(text(f"INSERT INTO `{table}` ({names}) VALUES ({params})"), cols).lastrowid


with engine.begin() as conn:
    if conn.execute(text("SELECT COUNT(*) FROM vendors WHERE vendor_email LIKE '%@seed.example.test'")).scalar():
        sys.exit("Donnees fictives deja presentes : rien fait.")

    # --- pays / villes ------------------------------------------------------
    for cid, name, code, calling, svc in [(217, "Togo", "TG", "228", "1"), (23, "Benin", "BJ", "229", "1"), (52, "Cote d'Ivoire", "CI", "225", "0")]:
        if not conn.execute(text("SELECT 1 FROM countries WHERE country_id=:i"), {"i": cid}).first():
            conn.execute(text("INSERT INTO countries (country_id,country_name,country_is_active,country_code,country_calling_codes,country_has_service) VALUES (:i,:n,1,:c,:k,:s)"), {"i": cid, "n": name, "c": code, "k": calling, "s": svc})
    lome = ins(conn, "cities", city_name="Lome", city_country_id=217, city_is_active=1)

    # --- catalogue ----------------------------------------------------------
    cat_repair = ins(conn, "categories", cat_name_fr="Reparation Installation", cat_name_en="Repair & Installation", cat_desp_fr="-", cat_desp_en="-", cat_image="uploads/category/seed1.png", cat_order=1, cat_is_active=1)
    cat_home = ins(conn, "categories", cat_name_fr="Aide a domicile", cat_name_en="Home help", cat_desp_fr="-", cat_desp_en="-", cat_image="uploads/category/seed2.png", cat_order=2, cat_is_active=1)
    cat_clean = ins(conn, "categories", cat_name_fr="Nettoyage", cat_name_en="Cleaning", cat_desp_fr="-", cat_desp_en="-", cat_image="uploads/category/seed3.png", cat_order=3, cat_is_active=1)
    subs = {}
    for key, fr, en, cat in [("plomberie", "Plomberie", "Plumbing", cat_repair), ("electricite", "Electricite", "Electricity", cat_repair), ("nettoyage", "Nettoyage maison", "House cleaning", cat_clean), ("garde", "Garde d'enfants", "Childcare", cat_home), ("cuisine", "Cuisine & traiteur", "Catering", cat_home), ("clim", "Climatisation", "Air conditioning", cat_repair)]:
        subs[key] = ins(conn, "sub_categories", subcat_name_fr=fr, subcat_name_en=en, subcat_desp_fr="-", subcat_desp_en="-", subcat_image=f"uploads/subcategory/seed_{key}.jpeg", subcat_cat_id=cat, subcat_is_active=1)

    # --- referentiel Academy ------------------------------------------------
    niveau_ids = {}
    for key, nom in [("plomberie", "Plomberie"), ("garde", "Garde d'enfants"), ("nettoyage", "Nettoyage")]:
        mid = ins(conn, "academy_metiers", id=subs[key], code=key, nom=nom, description="seed", nom_en=nom, description_en="seed", is_active=1)
        for num in (1, 2):
            niveau_ids[(key, num)] = ins(conn, "academy_niveaux", metier_id=mid, numero=num, nom=f"{nom} niveau {num}", description="seed", nom_en=f"{nom} level {num}", description_en="seed")

    # --- prestataires fictifs ---------------------------------------------
    people = [
        ("Kossi Amouzou", "plomberie", "certified_provider", 1, 4.9, 212), ("Mawuli Dossou", "plomberie", "certified_provider", 1, 4.8, 120),
        ("Sena Bokor", "electricite", "certified_provider", 1, 4.9, 160), ("Palakiyem Agba", "garde", "certified_provider", 1, 4.7, 71),
        ("Afi Mensah", "garde", "certified_provider", 1, 5.0, 96), ("Essi Kodjo", "nettoyage", "certified_provider", 1, 4.9, 308),
        ("Yao Dzidula", "electricite", "certified_provider", 0, 0, 0), ("Ama Tete", "cuisine", "apprentice", 0, 0, 0),
        ("Komi Lawson", "clim", None, 0, 4.2, 15), ("Edem Atsu", "plomberie", None, 0, 0, 3),
    ]
    vendor_ids = []
    for i, (name, svc, status, verified, mark, jobs) in enumerate(people, 1):
        vid = ins(conn, "vendors", vendor_unique_id=f"SEED{i:04d}", vendor_name=name, vendor_email=f"seed{i}@seed.example.test", vendor_phone=f"+2289000{i:04d}",
                  vendor_bio=f"Prestataire fictif {name}", vendor_image=f"https://example.test/p/{i}.jpg", vendor_address_city="Lome", vendor_country_id=217, vendor_city_id=lome,
                  vendor_is_active=1, vendor_mark=mark, vendor_jobs_count=jobs, vendor_sign_up_at=NOW - timedelta(days=30 * i), vendor_created_at=NOW - timedelta(days=30 * i),
                  vendor_academy_status=status, vendor_academy_verified=verified, vendor_academy_verified_at=NOW if verified else None, vendor_latitude=6.13 + i / 1000, vendor_longitude=1.22 + i / 1000)
        vendor_ids.append(vid)
        ins(conn, "services", s_subcat_id=str(subs[svc]), s_district_id="1", s_vendor_id=str(vid), s_tools_used="-", s_title=f"Service {svc}", s_desp="-", s_exp="5", s_sub_services="-", s_min_price=5000 + i * 500, s_is_active="1", s_options="-", s_country_id="217", s_city_id=str(lome), s_created_at=NOW)
        if status == "certified_provider" and svc in ("plomberie", "garde", "nettoyage"):
            ins(conn, "academy_certifications", vendor_id=vid, niveau_id=niveau_ids[(svc, 1)], code=f"{svc}_niveau_1", taxonomy_version=1, delivree_at=NOW)
        if status:
            ins(conn, "academy_trust_scores", vendor_id=vid, score_pct=60 + i, rules_score=60 + i, rules_breakdown_json="{}", justification="seed", computed_at=NOW)

    # --- clients, reservations, notes ---------------------------------------
    client_ids = [ins(conn, "clients", client_unique_id=f"SEEDC{i:03d}", client_name=f"Client Fictif {i}", client_email=f"client{i}@seed.example.test", client_phone=f"+2289100{i:04d}") for i in range(1, 5)]
    for n in range(12):
        v = vendor_ids[n % 6]
        bid = ins(conn, "bookings", bk_unique_id=f"SEEDBK{n:03d}", bk_client_id=client_ids[n % 4], bk_vendor_id=v, bk_selected_time="14:00", bk_total_amount="8000", bk_amount_paid="8000", bk_time="14:00", bk_address="Lome", bk_payment_method="mobile_money", bk_qty="1", bk_service_status="2", bk_date=NOW.date(), bk_created_at=NOW)
        if n % 2 == 0:
            ins(conn, "booking_marks", bk_mk_booking_id=bid, bk_mk_value=5 if n % 4 == 0 else 4, bk_mk_comment=f"Tres bien (fictif {n})", bk_mk_state="0", bk_mk_created_at=NOW)

    # --- avis Academy deja existants (v1) ----------------------------------
    for k in range(3):
        ins(conn, "academy_reviews", vendor_id=vendor_ids[k], client_id=client_ids[k], rating=5 - k % 2, comment=f"Avis v1 fictif {k}", created_at=NOW)

    # --- contenu & bannieres (v1) -------------------------------------------
    for k in range(1, 4):
        ins(conn, "academy_banners", ordre=k, image_url=f"https://example.test/banner{k}.jpg", image_url_mobile=None, is_active=1, created_at=NOW, updated_at=NOW)
    conn.execute(text("INSERT INTO academy_content_sections (`key`,title,subtitle,title_en,subtitle_en,is_active,updated_at) VALUES ('home_careers','Nos metiers','Choisissez un metier','Our careers','Pick a career',1,:n)"), {"n": NOW})
    for k in range(4):
        ins(conn, "events", event_title=f"Evenement fictif {k}", event_description="-", event_content="-", event_image="https://example.test/e.jpg", event_start_date=NOW.date(), event_end_date=NOW.date(), event_is_active=1, event_created_at=NOW, event_category="Formation")

print("Donnees fictives v1 inserees.")
