"""Inscription en 3 ecrans (apprenant / prestataire / client) : controle -> choix du canal -> code.
Base DEV uniquement ; nettoie tout ce qu'il cree.

Usage : PYTHONPATH=. python3 scripts/dev_signup_test.py"""
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
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import delivery  # noqa: E402

limiter.enabled = False
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
digits = "".join(str(int(ch, 16) % 10) for ch in tag)
failures: list[str] = []
phones: list[str] = []
emails: list[str] = []
PW = "Zephyr-Mango-" + tag + "!"
A = "/api/v1/auth"


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:200]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    db.rollback()
    return db


def ph(n):
    return f"+22890{digits[:4]}{n:02d}"


def body(role, n, **kw):
    b = {"role": role, "firstname": "Kodjo", "lastname": "", "password": PW, "phone": ph(n), "channel": "sms", "elapsed_ms": 4000}
    b.update(kw)
    phones.append(b["phone"])
    return b


try:
    print("Ecran 1 : controle des informations (rien n'est envoye)")
    before = len(delivery.OUTBOX)
    r = c.post(f"{A}/signup/check", json=body("apprenant", 1))
    check("apprenant sans email : accepte", r.status_code == 200, r.text)
    j = r.json()
    check("canaux : WhatsApp + SMS seulement (pas d'email)", j["channels"] == ["whatsapp", "sms"] and "email" not in j["destinations"], j)
    check("destinations masquees", all("*" in v for v in j["destinations"].values()), j["destinations"])
    check("aucun code envoye par le controle", len(delivery.OUTBOX) == before)
    em = f"sig-{tag}-a@example.com"
    r = c.post(f"{A}/signup/check", json=body("apprenant", 1, email=em))
    check("avec email : le canal email apparait", r.status_code == 200 and "email" in r.json()["channels"], r.text)
    check("client sans email : refuse", c.post(f"{A}/signup/check", json=body("client", 2)).status_code == 422)
    check("client avec email : accepte", c.post(f"{A}/signup/check", json=body("client", 2, email=f"sig-{tag}-c@example.com")).status_code == 200)
    check("prestataire sans email : accepte (metier / ville facultatifs)", c.post(f"{A}/signup/check", json=body("prestataire", 3)).status_code == 200)
    check("telephone invalide refuse", c.post(f"{A}/signup/check", json=body("apprenant", 4, phone="123")).status_code in (422,))
    check("mot de passe contenant le prenom refuse", c.post(f"{A}/signup/check", json=body("apprenant", 5, firstname="Kodjo", password="Kodjo-Zephyr-2026!")).status_code == 422)
    check("mot de passe courant refuse", c.post(f"{A}/signup/check", json=body("apprenant", 5, password="password123")).status_code == 422)

    print("Anti-robots")
    r = c.post(f"{A}/signup/check", json=body("apprenant", 6, hp="http://spam.example"))
    check("champ piege rempli -> refuse sans detail utile", r.status_code == 400 and "robot" not in r.text.lower(), r.text)
    check("formulaire rempli trop vite -> refuse", c.post(f"{A}/signup/check", json=body("apprenant", 6, elapsed_ms=200)).status_code == 400)
    check("blocages journalises", fresh().execute(text("SELECT COUNT(*) FROM academy_security_events WHERE event='signup_bot_blocked' AND created_at >= NOW() - INTERVAL 5 MINUTE")).scalar() >= 2)

    print("Ecran 2 : choix du canal")
    check("canal email sans email -> refuse", c.post(f"{A}/signup/start", json=body("apprenant", 7, channel="email")).status_code == 422)
    r = c.post(f"{A}/signup/start", json=body("apprenant", 7, channel="sms"))
    check("code envoye par le canal choisi (SMS)", r.status_code == 200 and r.json()["channel"] == "sms", r.text)

    print("Ecran 3 : code -> compte")
    code = delivery.OUTBOX[-1]["code"]
    check("code envoye a un numero (pas a un email)", delivery.OUTBOX[-1]["channel"] == "sms")
    check("mauvais code refuse", c.post(f"{A}/signup/verify", json={"request_id": r.json()["request_id"], "code": "000000"}).status_code in (400, 401, 422))
    v = c.post(f"{A}/signup/verify", json={"request_id": r.json()["request_id"], "code": code})
    check("compte apprenant cree sans email", v.status_code == 201 and v.json()["access_token"], v.text)
    row = fresh().execute(text("SELECT vendor_name, vendor_email, vendor_academy_status, vendor_country_code FROM vendors WHERE vendor_phone LIKE :p"), {"p": f"%{ph(7)[-8:]}"}).first()
    check("nom = prenoms seuls, email vide, statut apprentice, pays TG", row and row[0] == "Kodjo" and row[1] in (None, "") and row[2] == "apprentice" and row[3] == "TG", tuple(row) if row else None)

    print("Un email absent n'est jamais compare a NULL")
    r = c.post(f"{A}/signup/start", json=body("apprenant", 8, channel="whatsapp"))
    v = c.post(f"{A}/signup/verify", json={"request_id": r.json()["request_id"], "code": delivery.OUTBOX[-1]["code"]})
    check("2e compte sans email accepte (pas de faux doublon)", v.status_code == 201, v.text)
    check("meme numero : refuse des l'ecran 1", c.post(f"{A}/signup/check", json=body("apprenant", 8)).status_code == 400)
    check("connexion par telephone fonctionne sans email", c.post(f"{A}/login", json={"phone": ph(8), "password": PW}).status_code == 200)

    print("Prestataire et client")
    r = c.post(f"{A}/signup/start", json=body("prestataire", 9, channel="whatsapp"))
    v = c.post(f"{A}/signup/verify", json={"request_id": r.json()["request_id"], "code": delivery.OUTBOX[-1]["code"]})
    prow = fresh().execute(text("SELECT vendor_academy_status FROM vendors WHERE vendor_phone LIKE :p"), {"p": f"%{ph(9)[-8:]}"}).first()
    check("prestataire cree avec les 4 champs seulement", v.status_code == 201 and prow and prow[0] == "provider", v.text)
    cem = f"sig-{tag}-c@example.com"
    emails.append(cem)
    r = c.post(f"{A}/signup/start", json=body("client", 10, email=cem, channel="email"))
    check("client : code par email", r.status_code == 200 and delivery.OUTBOX[-1]["channel"] == "email" and delivery.OUTBOX[-1]["destination"] == cem, r.text)
    v = c.post(f"{A}/signup/verify", json={"request_id": r.json()["request_id"], "code": delivery.OUTBOX[-1]["code"]})
    check("compte client cree", v.status_code == 201, v.text)
    check("meme email : refuse a l'ecran 1", c.post(f"{A}/signup/check", json=body("client", 11, email=cem)).status_code == 400)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()
    suffixes = [p[-8:] for p in phones]
    for suf in suffixes:
        vids = [r[0] for r in db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_phone LIKE :p"), {"p": f"%{suf}"}).fetchall()]
        for vid in vids:
            for q in ("DELETE FROM academy_provider_profiles WHERE vendor_id=:i", "DELETE FROM academy_trust_scores WHERE vendor_id=:i",
                      "DELETE FROM academy_account_security WHERE role='apprenant' AND account_id=:i", "DELETE FROM academy_security_events WHERE role='apprenant' AND account_id=:i",
                      "DELETE FROM academy_trusted_devices WHERE role='apprenant' AND account_id=:i", "DELETE FROM vendors WHERE vendor_id=:i"):
                db.execute(text(q), {"i": vid})
        cids = [r[0] for r in db.execute(text("SELECT client_id FROM clients WHERE client_phone LIKE :p"), {"p": f"%{suf}"}).fetchall()]
        for cid in cids:
            for q in ("DELETE FROM academy_account_security WHERE role='client' AND account_id=:i", "DELETE FROM academy_security_events WHERE role='client' AND account_id=:i",
                      "DELETE FROM academy_trusted_devices WHERE role='client' AND account_id=:i", "DELETE FROM clients WHERE client_id=:i"):
                db.execute(text(q), {"i": cid})
    db.execute(text("DELETE FROM academy_verifications WHERE destination LIKE :a OR destination LIKE :b"), {"a": f"%{digits[:4]}%", "b": f"%sig-{tag}%"})
    db.execute(text("DELETE FROM academy_security_events WHERE event='signup_bot_blocked' AND created_at >= NOW() - INTERVAL 30 MINUTE"))
    db.commit()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
