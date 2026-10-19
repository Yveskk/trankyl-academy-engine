"""Espace "Mon compte" du client : profil, identifiants, mot de passe, activite, fermeture.
Base DEV uniquement ; nettoie tout.   Usage : PYTHONPATH=. python3 scripts/dev_client_account_test.py"""
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce n'est pas une base dev.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

limiter.enabled = False
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
ids: list[int] = []
PW = "Zephyr-Mango-1!"
M = "/api/v1/auth/client/me"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:200]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def mk(n):
    email, phone = f"cac-{tag}-{n}@example.com", f"+22891{tag[:3].translate(str.maketrans('abcdef', '123456'))}{n:03d}"
    db.execute(text("INSERT INTO clients (client_unique_id, client_name, client_email, client_password, client_phone, client_is_active) VALUES (:u,:n,:e,:p,:ph,1)"), {"u": f"CLI{tag}{n}", "n": f"Cora Durand{n}", "e": email, "p": hash_password(PW), "ph": phone})
    db.commit()
    cid = db.execute(text("SELECT client_id FROM clients WHERE client_email=:e"), {"e": email}).scalar()
    ids.append(cid)
    return cid, email, phone, {"Authorization": "Bearer " + create_access_token(subject=str(cid), role="client")}


try:
    cid, email, phone, H = mk(1)
    cid2, email2, phone2, H2 = mk(2)
    check("sans jeton : 401", c.patch(M, json={"firstname": "X"}).status_code == 401)
    r = c.patch(M, headers=H, json={"firstname": "Coralie", "lastname": "Martin"})
    check("changer le nom sans mot de passe", r.status_code == 200 and r.json()["firstname"] == "Coralie" and r.json()["lastname"] == "Martin", r.text)
    check("prenom vide refuse", c.patch(M, headers=H, json={"firstname": "   "}).status_code == 422)
    check("e-mail : mot de passe exige", c.patch(M, headers=H, json={"email": f"cac-{tag}-new@example.com"}).status_code == 403)
    check("e-mail : mauvais mot de passe", c.patch(M, headers=H, json={"email": f"cac-{tag}-new@example.com", "current_password": "Faux-1234!"}).status_code == 403)
    check("e-mail deja pris -> 400", c.patch(M, headers=H, json={"email": email2, "current_password": PW}).status_code == 400)
    check("telephone deja pris -> 400", c.patch(M, headers=H, json={"phone": phone2, "current_password": PW}).status_code == 400)
    check("telephone invalide -> 422", c.patch(M, headers=H, json={"phone": "abc", "current_password": PW}).status_code == 422)
    new_email = f"cac-{tag}-new@example.com"
    r = c.patch(M, headers=H, json={"email": new_email.upper(), "current_password": PW})
    check("changer l'e-mail (normalise en minuscules)", r.status_code == 200 and r.json()["email"] == new_email, r.text)
    same = c.patch(M, headers=H, json={"email": new_email, "phone": phone})
    check("renvoyer les memes valeurs : pas de mot de passe requis", same.status_code == 200, same.text)

    print("Mot de passe")
    NP = "Quartz-Lemon-77!"
    check("mauvais mot de passe actuel", c.post(f"{M}/password", headers=H, json={"current_password": "Faux-1234!", "new_password": NP}).status_code == 403)
    check("mot de passe faible refuse", c.post(f"{M}/password", headers=H, json={"current_password": PW, "new_password": "12345678"}).status_code == 422)
    check("identique a l'actuel refuse", c.post(f"{M}/password", headers=H, json={"current_password": PW, "new_password": PW}).status_code == 422)
    check("changement accepte", c.post(f"{M}/password", headers=H, json={"current_password": PW, "new_password": NP}).status_code == 200)
    lg = c.post("/api/v1/auth/client/login", json={"phone": phone, "password": NP, "lang": "fr"})
    check("connexion avec le nouveau mot de passe (ancien refuse)", lg.status_code == 200 and c.post("/api/v1/auth/client/login", json={"phone": phone, "password": PW, "lang": "fr"}).status_code == 401, lg.text)

    print("Photo de profil")
    import app.api.v1.endpoints.auth as authmod
    sent = []
    authmod.upload_image = lambda content, ctype: (sent.append(ctype), "https://res.cloudinary.com/demo/image/upload/avatar.jpg")[1]  # aucun envoi reel vers Cloudinary
    JPG = b"\xff\xd8\xff\xe0" + b"0" * 200
    PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    r = c.post(f"{M}/photo", headers=H, files={"file": ("a.jpg", JPG, "image/jpeg")})
    check("photo JPEG acceptee, URL enregistree", r.status_code == 200 and r.json()["image"].startswith("https://") and sent == ["image/jpeg"], r.text)
    check("visible via /me", c.get(M, headers=H).json()["image"].startswith("https://"))
    r = c.post(f"{M}/photo", headers=H, files={"file": ("a.png", PNG, "image/jpeg")})
    check("type detecte d'apres le contenu (pas l'en-tete)", r.status_code == 200 and sent[-1] == "image/png")
    check("faux fichier image refuse", c.post(f"{M}/photo", headers=H, files={"file": ("x.jpg", b"<?php echo 1;", "image/jpeg")}).status_code == 422)
    check("fichier trop gros refuse", c.post(f"{M}/photo", headers=H, files={"file": ("x.jpg", JPG + b"0" * (3 * 1024 * 1024), "image/jpeg")}).status_code == 413)
    check("sans jeton : 401", c.post(f"{M}/photo", files={"file": ("a.jpg", JPG, "image/jpeg")}).status_code == 401)
    check("suppression de la photo", c.delete(f"{M}/photo", headers=H).json()["image"] is None)
    db.execute(text("UPDATE clients SET client_image='uploads/ancienne.jpg' WHERE client_id=:i"), {"i": cid})
    db.commit()
    check("ancienne valeur relative : pas d'image", c.get(M, headers=H).json()["image"] is None)

    print("Activite et appareils")
    act = c.get(f"{M}/activity", headers=H).json()
    labels = {a["label"] for a in act}
    check("journal : mot de passe et profil modifies", {"Mot de passe modifié", "Profil modifié"} <= labels, labels)
    check("appareils de confiance oublies", c.post(f"{M}/devices/revoke", headers=H).status_code == 200)

    print("Fermeture du compte")
    check("fermeture : mot de passe exige", c.post(f"{M}/close", headers=H2, json={"password": "Faux-1234!"}).status_code == 403)
    db.execute(text("INSERT INTO bookings (bk_unique_id, bk_client_id, bk_service_status, bk_plateform, bk_client_name) VALUES (:u,:c,'0','academy','Cora')"), {"u": f"TB{tag}", "c": cid2})
    db.commit()
    r = c.post(f"{M}/close", headers=H2, json={"password": PW})
    check("reservation en cours : fermeture refusee (409)", r.status_code == 409, r.text)
    db.execute(text("UPDATE bookings SET bk_service_status='4' WHERE bk_unique_id=:u"), {"u": f"TB{tag}"})
    db.commit()
    check("fermeture acceptee", c.post(f"{M}/close", headers=H2, json={"password": PW}).status_code == 200)
    db.rollback()
    check("compte desactive, rien de supprime", db.execute(text("SELECT client_is_active FROM clients WHERE client_id=:i"), {"i": cid2}).scalar() in (0, False) and db.execute(text("SELECT COUNT(*) FROM bookings WHERE bk_unique_id=:u"), {"u": f"TB{tag}"}).scalar() == 1)
    check("jeton d'un compte ferme : 401", c.get(M, headers=H2).status_code == 401)
    check("connexion impossible", c.post("/api/v1/auth/client/login", json={"phone": phone2, "password": PW, "lang": "fr"}).status_code in (401, 403))
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    db.execute(text("DELETE FROM bookings WHERE bk_unique_id=:u"), {"u": f"TB{tag}"})
    for cid in ids:
        for q in ("DELETE FROM academy_account_security WHERE role='client' AND account_id=:i", "DELETE FROM academy_security_events WHERE role='client' AND account_id=:i",
                  "DELETE FROM academy_trusted_devices WHERE role='client' AND account_id=:i", "DELETE FROM clients WHERE client_id=:i"):
            db.execute(text(q), {"i": cid})
    db.commit()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
