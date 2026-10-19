"""Espace prestataire : profil -> formulaire d'enrolement -> tableau de bord, et menu admin « Formulaires d'enrolement ».
Base DEV uniquement ; AUCUN e-mail ni fichier n'est reellement envoye. Nettoie tout.

Usage : PYTHONPATH=. python3 scripts/dev_provider_space_test.py"""
import base64
import io
import json
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

from app.api.v1.endpoints.directory import clear_directory_cache  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services import enrollment_files as ef  # noqa: E402
from app.services.security import delivery  # noqa: E402
import app.api.v1.endpoints.provider_space as ps  # noqa: E402
from scripts._admin_login import admin_login_flow  # noqa: E402

limiter.enabled = False
settings.admin_email = "ops@example.test"
SENT: list[str] = []
ef._send = lambda data, label="Fichier": (SENT.append(label), f"https://res.cloudinary.com/demo/raw/upload/{len(SENT)}.png")[1]  # aucun envoi reel
ps.upload_image = lambda data, kind: "https://res.cloudinary.com/demo/image/upload/avatar.jpg"
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
vendor_emails: list[str] = []
admin_emails: list[str] = []
role_ids: list[int] = []
PW = "Zephyr-Mango-" + tag + "!"
P = "/api/v1/provider-space"
E = "/api/v1/enrollment-forms"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:230]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    try:
        db.rollback()
    except Exception:
        db.close()
    return db


def phone(n):
    return f"+22890{tag[:3].translate(str.maketrans('abcdef', '123456'))}{n:03d}"


def signup(email, n, country="TG", role="prestataire"):
    r = c.post("/api/v1/auth/signup/start", json={"role": role, "firstname": "Prune", "lastname": "Plombier", "email": email, "password": PW, "phone": phone(n), "channel": "email"}, headers={"X-Country": country})
    v = c.post("/api/v1/auth/signup/verify", json={"request_id": r.json()["request_id"], "code": delivery.OUTBOX[-1]["code"]}, headers={"X-Country": country})
    return v.json()["access_token"]


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 300
PDF = b"%PDF-1.4\n" + b"0" * 300
SIG = "data:image/png;base64," + base64.b64encode(PNG).decode()
try:
    # signature reelle (image valide) pour le contrat
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
    ImageDraw.Draw(im).line((5, 60, 90, 10, 190, 50), fill="black", width=3)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    SIG = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    em = f"pse-{tag}-p@example.com"
    vendor_emails.append(em)
    tok = signup(em, 1)
    H = {"Authorization": "Bearer " + tok}

    print("Acces et etat initial")
    check("sans jeton : 401", c.get(f"{P}/onboarding").status_code == 401)
    ap = signup(f"pse-{tag}-a@example.com", 2, role="apprenant")
    vendor_emails.append(f"pse-{tag}-a@example.com")
    check("un apprenant (non prestataire) : 403", c.get(f"{P}/onboarding", headers={"Authorization": "Bearer " + ap}).status_code == 403)
    st = c.get(f"{P}/onboarding", headers=H).json()
    check("etat initial : profil a completer", st["next_step"] == "profile" and not st["profile"]["complete"] and not st["dashboard_unlocked"], st)
    check("tableau de bord verrouille (409)", c.get(f"{P}/dashboard", headers=H).status_code == 409)
    check("enrolement impossible avant le profil (409)", c.put(f"{P}/enrollment", headers=H, data={"study_level": "lycee"}).status_code == 409)
    opts = c.get(f"{P}/options", headers=H).json()
    check("listes : pays", len(opts["countries"]) >= 1 and {"id", "name"} <= set(opts["countries"][0]), opts["countries"][:1])
    cid = next((x["id"] for x in opts["countries"] if x["name"] == "Togo"), opts["countries"][0]["id"])  # pays du profil = pays du prestataire = celui de la liste admin consultee (TG)

    print("Profil (memes champs que l'ancien site)")
    r = c.put(f"{P}/profile", headers=H, data={"fname": "Prune"})
    errs = r.json()["detail"]["errors"] if r.status_code == 422 else {}
    check("champs obligatoires signales", r.status_code == 422 and {"family_name", "email", "sex", "dob", "vendor_address_country", "vendor_address_city"} <= set(errs), r.text)
    full = {"fname": "Prune", "family_name": "Plombier", "email": em, "sex": "Female", "dob": "1990-05-17", "vendor_address_country": str(cid), "vendor_address_city": "Lomé", "address": "Rue 12, Tokoin", "bio": "Plombière <b>sérieuse</b>", "if_company": "0"}
    if opts["currencies"]:
        full["vendor_currency"] = str(opts["currencies"][0]["id"])
    check("date de naissance invalide refusee", c.put(f"{P}/profile", headers=H, data={**full, "dob": "2999-01-01"}).status_code == 422)
    check("e-mail invalide refuse", c.put(f"{P}/profile", headers=H, data={**full, "email": "pas-un-email"}).status_code == 422)
    r = c.put(f"{P}/profile", headers=H, data=full, files={"image": ("a.png", PNG, "image/png")})
    check("profil enregistre (+ photo)", r.status_code == 200 and r.json()["complete"] and r.json()["image"].startswith("https://") and r.json()["dob"] == "1990-05-17", r.text)
    row = fresh().execute(text("SELECT vendor_name, vendor_family_name, vendor_sex, vendor_dob, vendor_if_prof_comp FROM vendors WHERE vendor_email=:e"), {"e": em}).first()
    check("enregistre comme l'ancien site (prenoms / nom / F / JJ-MM-AAAA / profil complet)", tuple(row) == ("Prune", "Plombier", "F", "17-05-1990", "1"), tuple(row))
    cty = fresh().execute(text("SELECT vendor_country_id FROM vendors WHERE vendor_email=:e"), {"e": em}).scalar()
    check("le pays du profil devient le pays du prestataire (liste admin par pays)", cty == cid, cty)
    me = c.get("/api/v1/auth/me", headers=H).json()
    check("le nom s'affiche correctement dans Academy", me["firstname"] == "Prune" and me["lastname"] == "Plombier", me)
    check("etape suivante : enrolement", c.get(f"{P}/onboarding", headers=H).json()["next_step"] == "enrollment")
    check("photo non-image refusee", c.put(f"{P}/profile", headers=H, data=full, files={"image": ("a.png", b"<?php echo 1;", "image/png")}).status_code == 422)

    print("Formulaire d'enrolement")
    r = c.put(f"{P}/enrollment", headers=H, data={"is_professional": "1", "study_level": "licence", "languages": "Français, Anglais"})
    check("brouillon enregistre (status draft)", r.status_code == 200 and r.json()["enrollment"]["status"] == "draft" and r.json()["enrollment"]["study_level"] == "licence", r.text)
    check("aucun e-mail pour un simple brouillon", not [m for m in delivery.OUTBOX if m.get("purpose") == "enrollment_admin"])
    check("valeur invalide refusee", c.put(f"{P}/enrollment", headers=H, data={"study_level": "nimporte"}).status_code == 422)
    check("langue invalide refusee", c.put(f"{P}/enrollment", headers=H, data={"languages": "Klingon"}).status_code == 422)
    r = c.post(f"{P}/enrollment/submit", headers=H)
    labels = [m["label"] for m in r.json()["detail"]["missing"]] if r.status_code == 422 else []
    check("soumission refusee : donnees importantes manquantes", r.status_code == 422 and {"Type de pièce", "Pièce d'identité (recto)", "Signature du contrat"} <= set(labels), r.text)
    check("faux fichier refuse (contenu reel verifie)", c.put(f"{P}/enrollment", headers=H, data={"id_type": "CNI"}, files={"id_file": ("x.jpg", b"<?php echo 1;", "image/jpeg")}).status_code == 422)
    check("fichier trop gros refuse", c.put(f"{P}/enrollment", headers=H, data={"id_type": "CNI"}, files={"id_file": ("x.pdf", PDF + b"0" * (5 * 1024 * 1024), "application/pdf")}).status_code == 422)
    r = c.put(f"{P}/enrollment", headers=H, data={"id_type": "CNI", "id_number": "TG123456"}, files={"id_file": ("recto.png", PNG, "image/png")})
    check("recto envoye", r.status_code == 200 and r.json()["enrollment"]["id_file"].startswith("https://"))
    r = c.post(f"{P}/enrollment/submit", headers=H)
    labels = [m["label"] for m in r.json()["detail"]["missing"]]
    check("le verso est exige pour une CNI, pas pour un passeport", "Pièce d'identité (verso)" in labels)
    r = c.put(f"{P}/enrollment", headers=H, data={"id_type": "PASSEPORT"})
    check("passeport : verso non requis", "Pièce d'identité (verso)" not in [m["label"] for m in r.json()["missing"]])
    r = c.put(f"{P}/enrollment", headers=H, data={"if_company": "1"})
    miss = [m["label"] for m in r.json()["missing"]]
    check("entreprise : nom, secteur, forme juridique et registre exiges", {"Nom entreprise", "Secteur d'activité", "Forme juridique", "Registre de Commerce"} <= set(miss), miss)
    check("signature invalide refusee", c.put(f"{P}/enrollment", headers=H, data={"signature": "data:image/png;base64,AAAA"}).status_code == 422)
    r = c.put(f"{P}/enrollment", headers=H, data={"if_company": "0", "signature": SIG, "keep_diploma_files": "[]"}, files=[("diploma_files", ("d1.pdf", PDF, "application/pdf")), ("diploma_files", ("d2.png", PNG, "image/png"))])
    check("diplomes (2) + signature enregistres", r.status_code == 200 and len(r.json()["enrollment"]["diploma_files"]) == 2 and r.json()["enrollment"]["has_signature"], r.text)
    four = [("diploma_files", (f"d{i}.pdf", PDF, "application/pdf")) for i in range(2)]
    r = c.put(f"{P}/enrollment", headers=H, data={"keep_diploma_files": json.dumps(r.json()["enrollment"]["diploma_files"])}, files=four)
    check("3 fichiers maximum par rubrique", r.status_code == 422)
    r = c.put(f"{P}/enrollment", headers=H, data={"clear": json.dumps(["id_file_verso"])})
    check("une piece peut etre retiree", r.status_code == 200)

    delivery.OUTBOX.clear()
    r = c.post(f"{P}/enrollment/submit", headers=H)
    check("soumission acceptee", r.status_code == 200 and r.json()["enrollment_status"] == "pending", r.text)
    ms = [m for m in delivery.OUTBOX if m.get("purpose") == "enrollment_admin"]
    check("e-mail a l'administration (une seule fois, avec le nom)", len(ms) == 1 and ms[0]["destination"] == "ops@example.test" and "Prune Plombier" in ms[0]["html"] and "/admin/enrolements" in ms[0]["html"], [m["subject"] for m in ms])
    check("contrat signe genere", fresh().execute(text("SELECT enroll_contract_pdf FROM vendor_enrollments e JOIN vendors v ON v.vendor_id=e.enroll_vendor_id WHERE v.vendor_email=:e"), {"e": em}).scalar() is not None)
    check("dossier verrouille pendant l'examen (409)", c.put(f"{P}/enrollment", headers=H, data={"study_level": "master"}).status_code == 409 and c.post(f"{P}/enrollment/submit", headers=H).status_code == 409)
    st = c.get(f"{P}/onboarding", headers=H).json()
    check("tableau de bord debloque", st["dashboard_unlocked"] and st["next_step"] == "dashboard", st)
    d = c.get(f"{P}/dashboard", headers=H).json()
    check("tableau de bord : nom, ville, verification, statistiques", d["name"] == "Prune" and d["city"] == "Lomé" and d["verification"]["total"] == 7 and "revenue_month" in d["stats"] and d["enrollment_status"] == "pending", d)

    print("Admin : menu Formulaires d'enrolement")
    sa = f"pse-{tag}-super@example.com"
    admin_emails.append(sa)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sup','Er',:e,:p,1)"), {"e": sa, "p": hash_password("Sup3r-Pse-Pass!")})
    db.commit()
    t, _, _ = admin_login_flow(c, sa, "Sup3r-Pse-Pass!")
    AH = lambda country="TG": {"Authorization": f"Bearer {t}", "X-Country": country}  # noqa: E731
    lst = c.get(f"{E}/admin?q=Prune", headers=AH()).json()
    mine = [i for i in lst["items"] if i["email"] == em]
    check("le dossier soumis apparait dans la liste (statut en attente)", len(mine) == 1 and mine[0]["status"] == "pending" and lst["counts"]["pending"] >= 1, lst["counts"])
    eid = mine[0]["id"]
    check("liste d'un autre pays : absent", not [i for i in c.get(f"{E}/admin?q=Prune", headers=AH("CI")).json()["items"] if i["email"] == em])
    det = c.get(f"{E}/admin/{eid}", headers=AH()).json()
    keys = {f["key"]: f for g in det["groups"] for f in g["fields"]}
    check("detail : champs, fichiers, signature, contrat", keys["study_level"]["value"] == "Licence (Bac+3)" and keys["id_file"]["filled"] and len(keys["diploma_files"]["value"]) == 2 and det["signature"] and det["contract_pdf"] and not keys["casier_file"]["filled"], det)
    check("detail d'un autre pays -> 404", c.get(f"{E}/admin/{eid}", headers=AH("CI")).status_code == 404)
    check("refus sans motif -> 422", c.post(f"{E}/admin/{eid}/decision", headers=AH(), json={"status": "rejected"}).status_code == 422)
    delivery.OUTBOX.clear()
    r = c.post(f"{E}/admin/{eid}/decision", headers=AH(), json={"status": "rejected", "note": "Pièce illisible", "fields": ["Pièce d'identité (recto)", "Champ inconnu"]})
    check("refus avec motif et champs", r.status_code == 200)
    dm = [m for m in delivery.OUTBOX if m.get("purpose") == "enrollment_decision"]
    check("le prestataire est prevenu par e-mail (motif + champs refuses, HTML echappe)", len(dm) == 1 and dm[0]["destination"] == em and "Pièce illisible" in dm[0]["html"] and "Pièce d&#x27;identité (recto)" in dm[0]["html"] and "Champ inconnu" not in dm[0]["html"], dm and dm[0]["html"][:200])
    st = c.get(f"{P}/onboarding", headers=H).json()
    check("prestataire : refuse -> retour au formulaire, motif visible", st["enrollment"]["status"] == "rejected" and st["next_step"] == "enrollment" and st["enrollment"]["admin_note"] == "Pièce illisible", st)
    check("tableau de bord de nouveau verrouille", c.get(f"{P}/dashboard", headers=H).status_code == 409)
    r = c.put(f"{P}/enrollment", headers=H, files={"id_file": ("recto2.png", PNG, "image/png")}, data={"id_type": "PASSEPORT"})
    check("le prestataire peut corriger puis resoumettre", r.status_code == 200)
    delivery.OUTBOX.clear()
    r = c.post(f"{P}/enrollment/submit", headers=H)
    check("nouvelle soumission : alerte 'mis a jour'", r.status_code == 200 and [m for m in delivery.OUTBOX if m.get("purpose") == "enrollment_admin" and "mis à jour" in m["html"].lower()], r.text)
    delivery.OUTBOX.clear()
    r = c.post(f"{E}/admin/{eid}/decision", headers=AH(), json={"status": "approved", "fields": ["Casier judiciaire"]})
    check("approbation avec champs a completer", r.status_code == 200)
    am = [m for m in delivery.OUTBOX if m.get("purpose") == "enrollment_decision"]
    check("e-mail d'approbation avec la liste a completer", len(am) == 1 and "approuvé" in am[0]["subject"].lower() and "Casier judiciaire" in am[0]["html"], am and am[0]["subject"])
    ver = fresh().execute(text("SELECT vendor_academy_verified FROM vendors WHERE vendor_email=:e"), {"e": em}).scalar()
    check("approuve -> prestataire verifie", ver in (1, True))
    check("tableau de bord de nouveau accessible", c.get(f"{P}/dashboard", headers=H).status_code == 200)
    check("compteurs admin mis a jour", c.get(f"{E}/admin?status=approved&q=Prune", headers=AH()).json()["counts"]["approved"] >= 1)

    print("Permissions du menu")
    mk = lambda name, perms: c.post("/api/v1/access/roles", headers=AH(), json={"name": name, "permissions": perms, "countries": []}).json()  # noqa: E731
    rv, rn = mk(f"Lecture enr {tag}", ["academy.enrollment_forms.view"]), mk(f"Sans enr {tag}", ["academy.blog.view"])
    role_ids.extend([rv["id"], rn["id"]])

    def staff(n, role):
        e = f"pse-{tag}-s{n}@example.com"
        admin_emails.append(e)
        u = c.post("/api/v1/access/users", headers=AH(), json={"firstname": "Staff", "lastname": f"N{n}", "email": e, "role_id": role["id"], "countries": ["TG"]}).json()
        tt, _, _ = admin_login_flow(c, e, u["invitation"]["temp_password"], new_password="Zephyr-Mango-Quartz-7!")
        return {"Authorization": f"Bearer {tt}", "X-Country": "TG"}

    SV, SN = staff(1, rv), staff(2, rn)
    check("sans la permission : 403", c.get(f"{E}/admin", headers=SN).status_code == 403)
    check("lecture seule : liste et detail", c.get(f"{E}/admin", headers=SV).status_code == 200 and c.get(f"{E}/admin/{eid}", headers=SV).status_code == 200)
    check("lecture seule : decision refusee (403)", c.post(f"{E}/admin/{eid}/decision", headers=SV, json={"status": "approved"}).status_code == 403)
    check("sans jeton : 401", c.get(f"{E}/admin").status_code == 401)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    vids = [r[0] for r in db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_email IN :e").bindparams(bindparam("e", expanding=True)), {"e": vendor_emails or [""]}).fetchall()]
    if vids:
        for q in ("DELETE FROM vendor_enrollments WHERE enroll_vendor_id IN :i", "DELETE FROM academy_provider_profiles WHERE vendor_id IN :i", "DELETE FROM academy_trust_scores WHERE vendor_id IN :i",
                  "DELETE FROM academy_account_security WHERE role='apprenant' AND account_id IN :i", "DELETE FROM academy_security_events WHERE role='apprenant' AND account_id IN :i",
                  "DELETE FROM academy_trusted_devices WHERE role='apprenant' AND account_id IN :i", "DELETE FROM vendors WHERE vendor_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": vids})
    aids = [r[0] for r in db.execute(text("SELECT us_id FROM users WHERE email IN :e").bindparams(bindparam("e", expanding=True)), {"e": admin_emails or [""]}).fetchall()]
    if aids:
        for q in ("DELETE FROM academy_admin_countries WHERE user_id IN :i", "DELETE FROM academy_admin_profiles WHERE user_id IN :i", "DELETE FROM academy_account_security WHERE role='admin' AND account_id IN :i",
                  "DELETE FROM academy_security_events WHERE role='admin' AND account_id IN :i", "DELETE FROM academy_trusted_devices WHERE role='admin' AND account_id IN :i", "DELETE FROM users WHERE us_id IN :i"):
            db.execute(text(q).bindparams(bindparam("i", expanding=True)), {"i": aids})
    for rid in role_ids:
        db.execute(text("DELETE FROM academy_role_countries WHERE role_id=:i"), {"i": rid})
        db.execute(text("DELETE FROM user_types WHERE ust_id=:i AND ust_id<>1"), {"i": rid})
    db.execute(text("DELETE FROM academy_verifications WHERE destination LIKE :t"), {"t": f"%pse-{tag}%"})
    db.execute(text("DELETE FROM academy_security_events WHERE detail LIKE :t OR detail LIKE 'dossier %' AND created_at > NOW() - INTERVAL 1 DAY AND role='admin'"), {"t": f"%{tag}%"})
    db.commit()
    clear_directory_cache()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
