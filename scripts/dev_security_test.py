"""Test de bout en bout de la verification par code (inscription, connexion,
mot de passe oublie) sur la base DEV. Mode d'envoi "log" obligatoire : aucun
vrai message n'est envoye. Nettoie tout ce qu'il cree.
Usage : python -m scripts.dev_security_test"""
import os
import sys
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : base non dev.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import delivery  # noqa: E402

assert settings.otp_delivery_mode == "log", "mode d'envoi non 'log' : test annule"
limiter.enabled = False
settings.login_verification_policy = "new_device"  # la politique par defaut est « off » : ce test exerce explicitement le code sur appareil inconnu
settings.otp_resend_cooldown_seconds = 0
settings.otp_max_sends_per_hour_ip = 10_000
settings.otp_max_sends_per_hour_destination = 1000
settings.otp_max_sends_per_day_destination = 10_000

c = TestClient(app)
# READ COMMITTED : le test voit les ecritures faites par l'API (autres connexions) sans snapshot fige.
db = Session(bind=engine.execution_options(isolation_level="READ COMMITTED"))
tag = uuid.uuid4().hex[:8]
fails: list[str] = []
created_emails: list[str] = []


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL"), label, (f"[{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def last_code(channel=None):
    for m in reversed(delivery.OUTBOX):
        if channel is None or m["channel"] == channel:
            return m["code"]
    return None


def phone():
    return "+22891" + str(uuid.uuid4().int)[:6]


PW = "Soleil-2026-ok!"


def signup(role="client", channel="whatsapp", ph=None, email=None, pw=PW, extra=None):
    ph = ph or phone()
    email = email or f"sectest-{tag}-{uuid.uuid4().hex[:5]}@example.com"
    created_emails.append(email)
    body = {"role": role, "firstname": "Test", "lastname": "Securite", "email": email, "password": pw, "phone": ph, "channel": channel, **(extra or {})}
    return c.post("/api/v1/auth/signup/start", json=body), ph, email


try:
    print("Inscription : validations")
    r, ph, email = signup(pw="abc")
    check("mot de passe trop court -> 422", r.status_code == 422, r.text[:100])
    r, *_ = signup(pw="12345678")
    check("mot de passe courant -> 422", r.status_code == 422)
    r, *_ = signup(ph="12ab")
    check("telephone invalide -> 422", r.status_code == 422)
    r, ph_fr, email_fr = signup(ph="+33672824623")
    check("indicatif non autorise : WhatsApp/SMS refuses (choix explicite)", r.status_code == 422, r.text[:160])
    chk = c.post("/api/v1/auth/signup/check", json={"role": "client", "firstname": "Test", "lastname": "Securite", "email": email_fr, "password": PW, "phone": ph_fr})
    check("controle : seul le canal email est propose", chk.status_code == 200 and chk.json()["channels"] == ["email"], chk.text[:160])
    r, *_ = signup(ph="+33672824623", channel="email", email=email_fr)
    check("indicatif non autorise : code envoye par email", r.status_code == 200 and r.json()["channel"] == "email" and r.json()["channels"] == ["email"], r.text[:160])
    check("code recu par email dans l'outbox (mode log)", delivery.OUTBOX[-1]["channel"] == "email")

    print("Inscription : parcours complet (client)")
    delivery.OUTBOX.clear()
    r, ph1, email1 = signup()
    j = r.json()
    check("start -> verification_required", r.status_code == 200 and j["status"] == "verification_required" and j["channel"] == "whatsapp", r.text[:200])
    check("numero masque", "*" in j["destination_masked"] and ph1[-4:-2] not in j["destination_masked"] or j["destination_masked"].endswith(ph1[-2:]), j["destination_masked"])
    check("canaux proposes", set(j["channels"]) == {"whatsapp", "sms", "email"})
    check("le code n'est PAS dans la reponse", last_code() not in r.text)
    code = last_code("whatsapp")
    row = db.execute(text("SELECT code_hash, channel FROM academy_verifications WHERE request_id=:r"), {"r": j["request_id"]}).first()
    check("code stocke hache (jamais en clair)", row is not None and row[0] != code and len(row[0]) == 64)
    check("aucun compte cree avant verification", db.execute(text("SELECT COUNT(*) FROM clients WHERE client_email=:e"), {"e": email1}).scalar() == 0)
    wrong = "000000" if code != "000000" else "111111"
    r = c.post("/api/v1/auth/signup/verify", json={"request_id": j["request_id"], "code": wrong})
    check("mauvais code -> 400 + essais restants", r.status_code == 400 and r.json()["detail"]["attempts_left"] == 4, r.text[:160])
    r = c.post("/api/v1/auth/signup/verify", json={"request_id": j["request_id"], "code": code})
    check("bon code -> 201 + jeton", r.status_code == 201 and r.json()["access_token"] and r.json()["role"] == "client", r.text[:160])
    token = r.json()["access_token"]
    check("compte cree", db.execute(text("SELECT COUNT(*) FROM clients WHERE client_email=:e"), {"e": email1}).scalar() == 1)
    check("numero marque verifie", db.execute(text("SELECT COUNT(*) FROM academy_account_security s JOIN clients c ON c.client_id=s.account_id WHERE s.role='client' AND c.client_email=:e AND s.phone_verified_at IS NOT NULL"), {"e": email1}).scalar() == 1)
    check("jeton valable (/client/me)", c.get("/api/v1/auth/client/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200)
    r = c.post("/api/v1/auth/signup/verify", json={"request_id": j["request_id"], "code": code})
    check("code deja utilise -> refuse", r.status_code == 400 and r.json()["detail"]["code"] == "invalid")
    r, *_ = signup(ph=ph1)
    check("numero deja inscrit -> 400", r.status_code == 400)
    r, *_ = signup(email=email1)
    check("email deja inscrit -> 400", r.status_code == 400)

    print("Essais et renvoi")
    r, ph2, email2 = signup()
    j2 = r.json()
    code2 = last_code()
    for i in range(5):
        rr = c.post("/api/v1/auth/signup/verify", json={"request_id": j2["request_id"], "code": "000000" if code2 != "000000" else "111111"})
    check("5 mauvais essais -> verrouille", rr.status_code in (400, 429))
    rr = c.post("/api/v1/auth/signup/verify", json={"request_id": j2["request_id"], "code": code2})
    check("meme le bon code est refuse apres 5 essais", rr.status_code == 429 and rr.json()["detail"]["code"] == "too_many_attempts", rr.text[:120])
    rr = c.post("/api/v1/verification/resend".replace("/api/v1", "/api/v1/auth"), json={"request_id": j2["request_id"], "channel": "sms"})
    check("renvoi par SMS -> nouveau code, essais remis a zero", rr.status_code == 200 and rr.json()["channel"] == "sms" and delivery.OUTBOX[-1]["channel"] == "sms", rr.text[:120])
    rr = c.post("/api/v1/auth/signup/verify", json={"request_id": j2["request_id"], "code": last_code("sms")})
    check("nouveau code accepte", rr.status_code == 201, rr.text[:120])
    settings.otp_resend_cooldown_seconds = 60
    r, *_ = signup()
    j3 = r.json()
    rr = c.post("/api/v1/auth/verification/resend", json={"request_id": j3["request_id"]})
    check("delai de 60 s entre deux envois -> 429", rr.status_code == 429 and rr.json()["detail"]["code"] == "cooldown", rr.text[:120])
    settings.otp_resend_cooldown_seconds = 0
    rr = c.post("/api/v1/auth/verification/resend", json={"request_id": "x" * 36})
    check("demande inconnue -> generique", rr.status_code == 400 and rr.json()["detail"]["code"] == "invalid")
    old = signup()[1]  # remplir le plafond horaire pour un meme numero
    pnum = phone()
    settings.otp_max_sends_per_hour_destination, settings.otp_max_sends_per_day_destination = 5, 10
    codes = [signup(ph=pnum)[0].status_code for _ in range(6)]
    settings.otp_max_sends_per_hour_destination, settings.otp_max_sends_per_day_destination = 1000, 10_000
    check("plafond d'envois par destinataire (5/heure) -> 429", codes[:5] == [200] * 5 and codes[5] == 429, str(codes))

    print("Connexion")
    # le compte cree plus haut : client ph1 / PW
    def login(p=ph1, pw=PW, **kw):
        return c.post("/api/v1/auth/client/login", json={"phone": p, "password": pw, **kw})

    r = login(pw="mauvais-mot-de-passe")
    check("mauvais mot de passe -> 401", r.status_code == 401)
    r = login(p=phone(), pw="whatever-1234")
    check("numero inconnu -> meme 401 generique", r.status_code == 401 and r.json()["detail"] == "Telephone ou mot de passe incorrect")
    r = login()
    j = r.json()
    check("mot de passe OK, appareil inconnu -> code exige", r.status_code == 200 and j["status"] == "verification_required" and j["access_token"] is None, r.text[:160])
    r = c.post("/api/v1/auth/login/verify", json={"request_id": j["request_id"], "code": last_code(), "trust_device": True})
    d = r.json()
    check("code OK -> jeton + appareil de confiance", r.status_code == 200 and d["access_token"] and d["device_token"], r.text[:160])
    dev = d["device_token"]
    check("jeton d'appareil stocke hache", db.execute(text("SELECT COUNT(*) FROM academy_trusted_devices WHERE token_hash=:h"), {"h": dev}).scalar() == 0)
    r = login(device_token=dev)
    check("appareil reconnu -> connexion directe", r.status_code == 200 and r.json()["status"] == "ok" and r.json()["access_token"], r.text[:160])
    r = login(device_token="jeton-invente-" + "x" * 30)
    check("jeton d'appareil invalide -> code exige", r.json()["status"] == "verification_required")
    settings.login_verification_policy = "always"
    check("politique 'always' : code meme sur appareil connu", login(device_token=dev).json()["status"] == "verification_required")
    settings.login_verification_policy = "off"
    check("politique 'off' (coupe-circuit) : connexion directe", login().json()["status"] == "ok")
    settings.login_verification_policy = "new_device"

    print("Verrouillage")
    r2, ph4, e4 = signup()
    c.post("/api/v1/auth/signup/verify", json={"request_id": r2.json()["request_id"], "code": last_code()})
    statuses = [login(p=ph4, pw="Faux-mot-de-passe-1")]
    for _ in range(5):
        statuses.append(login(p=ph4, pw="Faux-mot-de-passe-1"))
    check("5 echecs -> verrouillage 429", statuses[4].status_code == 401 and statuses[5].status_code == 429, str([s.status_code for s in statuses]))
    check("verrouille meme avec le bon mot de passe", login(p=ph4).status_code == 429)
    db.execute(text("UPDATE academy_account_security s JOIN clients c ON c.client_id=s.account_id SET s.locked_until=NULL, s.failed_attempts=0 WHERE s.role='client' AND c.client_email=:e"), {"e": e4})
    db.commit()
    check("deverrouille apres delai", login(p=ph4).status_code == 200)

    print("Compte historique (jamais verifie)")
    legacy_ph = phone()
    legacy_email = f"sectest-{tag}-legacy@example.com"
    created_emails.append(legacy_email)
    db.execute(text("INSERT INTO clients (client_unique_id, client_name, client_email, client_phone, client_password, client_is_active) VALUES (:u,'Legacy Client',:e,:p,:h,1)"),
               {"u": "LEG" + tag, "e": legacy_email, "p": legacy_ph.lstrip("+"), "h": hash_password(PW)})
    db.commit()
    r = login(p=legacy_ph)
    check("compte sans ligne de securite -> verification, pas de blocage", r.status_code == 200 and r.json()["status"] == "verification_required", r.text[:140])
    r = c.post("/api/v1/auth/login/verify", json={"request_id": r.json()["request_id"], "code": last_code()})
    check("apres verification : connecte et numero marque verifie", r.status_code == 200 and r.json()["access_token"] is not None)

    print("Echec d'envoi : bascule de canal")
    real_send = delivery.send_code

    def failing(channel, destination, code, **kw):
        if channel == "whatsapp":
            raise delivery.DeliveryError("whatsapp", "WhatsApp est momentanement indisponible.")
        return real_send(channel, destination, code, **kw)

    import app.services.security.verification as vmod

    vmod.send_code = failing
    settings.login_verification_policy = "always"
    r = login()
    d = r.json()["detail"]
    check("WhatsApp en panne -> 502 avec request_id et canaux restants", r.status_code == 502 and d["request_id"] and "sms" in d["channels"], r.text[:200])
    r = c.post("/api/v1/auth/verification/resend", json={"request_id": d["request_id"], "channel": "sms"})
    check("bascule immediate sur SMS", r.status_code == 200 and r.json()["channel"] == "sms", r.text[:160])
    r = c.post("/api/v1/auth/login/verify", json={"request_id": d["request_id"], "code": last_code("sms")})
    check("connexion apres bascule", r.status_code == 200 and r.json()["access_token"])
    vmod.send_code = real_send
    settings.login_verification_policy = "new_device"

    print("Mot de passe oublie")
    r = c.post("/api/v1/auth/forgot-password", json={"identifier": phone(), "role": "client", "channel": "sms"})
    check("compte inconnu : meme forme de reponse, aucun envoi", r.status_code == 200 and r.json()["request_id"] and r.json()["status"] == "verification_required")
    delivery.OUTBOX.clear()
    c.post("/api/v1/auth/forgot-password", json={"identifier": phone(), "role": "client", "channel": "sms"})
    check("compte inconnu : rien dans l'outbox", len(delivery.OUTBOX) == 0)
    r = c.post("/api/v1/auth/forgot-password", json={"identifier": ph1, "role": "client", "channel": "whatsapp"})
    fj = r.json()
    check("compte connu : code envoye", r.status_code == 200 and delivery.OUTBOX and delivery.OUTBOX[-1]["purpose"] == "password_reset", r.text[:150])
    r = c.post("/api/v1/auth/verify-otp", json={"request_id": fj["request_id"], "code": "999999" if last_code() != "999999" else "888888"})
    check("mauvais code -> 400", r.status_code == 400)
    r = c.post("/api/v1/auth/verify-otp", json={"request_id": fj["request_id"], "code": last_code()})
    tok = r.json().get("reset_token")
    check("bon code -> jeton de reinitialisation", r.status_code == 200 and tok, r.text[:120])
    r = c.post("/api/v1/auth/reset-password", json={"reset_token": tok, "new_password": "12345678"})
    check("nouveau mot de passe trop faible -> 422", r.status_code == 422)
    NEW = "Nouveau-Secret-2027!"
    r = c.post("/api/v1/auth/reset-password", json={"reset_token": tok, "new_password": NEW})
    check("reinitialisation OK", r.status_code == 200, r.text[:100])
    r = c.post("/api/v1/auth/reset-password", json={"reset_token": tok, "new_password": "Autre-Secret-2028!"})
    check("jeton deja utilise -> 400", r.status_code == 400)
    check("ancien mot de passe refuse", login(pw=PW).status_code == 401)
    r = login(pw=NEW, device_token=dev)
    check("appareils de confiance revoques apres reset -> code exige", r.status_code == 200 and r.json()["status"] == "verification_required", r.text[:120])

    print("Administrateur")
    admin_email = f"sectest-{tag}-admin@example.com"
    made_type = not db.execute(text("SELECT 1 FROM user_types WHERE ust_id=1")).first()
    if made_type:
        db.execute(text("INSERT INTO user_types (ust_id, ust_wording, ust_description, ust_roles) VALUES (1,'Admin','test','[\"ADMIN\"]')"))
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Sec','Admin',:e,:p,1)"), {"e": admin_email, "p": hash_password(PW)})
    db.commit()
    r = c.post("/api/v1/auth/admin/login", json={"email": admin_email, "password": "faux"})
    check("admin : mauvais mot de passe -> 401", r.status_code == 401)
    r = c.post("/api/v1/auth/admin/login", json={"email": admin_email, "password": PW})
    aj = r.json()
    check("admin : code OBLIGATOIRE par email", r.status_code == 200 and aj["status"] == "verification_required" and aj["channel"] == "email" and aj["channels"] == ["email"], r.text[:200])
    r = c.post("/api/v1/auth/login/verify", json={"request_id": aj["request_id"], "code": last_code("email"), "trust_device": True})
    check("admin : code email OK -> pas de jeton, la 2FA doit etre configuree", r.status_code == 200 and r.json()["status"] == "mfa_setup_required" and not r.json().get("access_token") and r.json()["pre_token"], r.text[:150])
    from app.services.security import totp as _totp

    pre = r.json()["pre_token"]
    sj = c.post("/api/v1/auth/admin/mfa/setup", json={"pre_token": pre}).json()
    check("admin : secret TOTP + QR (otpauth)", sj["otpauth_uri"].startswith("otpauth://totp/") and len(sj["secret"]) >= 16)
    r = c.post("/api/v1/auth/admin/mfa/enable", json={"pre_token": pre, "code": "000000"})
    check("admin : mauvais code d'activation refuse", r.status_code == 401)
    r = c.post("/api/v1/auth/admin/mfa/enable", json={"pre_token": pre, "code": _totp.current_code(sj["secret"])})
    check("admin : 2FA activee -> jeton + 10 codes de secours", r.status_code == 200 and r.json()["access_token"] and len(r.json()["recovery_codes"] or []) == 10, r.text[:150])
    r = c.post("/api/v1/auth/admin/login", json={"email": admin_email, "password": PW})
    check("admin : ensuite mot de passe + code de l'application (plus d'email)", r.json()["status"] == "mfa_required")
    settings.login_verification_policy = "always"
    created_admin = admin_email

    print("Divers")
    r = c.post("/api/v1/auth/client/register", json={"firstname": "A", "lastname": "B", "email": f"x{tag}@example.com", "password": PW, "phone": phone()})
    check("ancienne inscription directe refusee (403)", r.status_code == 403)
    ev = db.execute(text("SELECT COUNT(*) FROM academy_security_events")).scalar()
    check("journal d'audit alimente", ev > 10, str(ev))
    leak = db.execute(text("SELECT COUNT(*) FROM academy_security_events WHERE detail LIKE '%000000%' OR detail LIKE :pw"), {"pw": f"%{PW}%"}).scalar()
    check("aucun mot de passe ni code dans le journal", leak == 0)
finally:
    settings.login_verification_policy = "new_device"
    emails = created_emails + [f"sectest-{tag}-admin@example.com"]
    for e in emails:
        db.execute(text("DELETE FROM clients WHERE client_email=:e"), {"e": e})
        db.execute(text("DELETE FROM vendors WHERE vendor_email=:e"), {"e": e})
        db.execute(text("DELETE FROM users WHERE email=:e"), {"e": e})
    db.execute(text("DELETE FROM academy_verifications WHERE JSON_VALID(payload_json) AND payload_json LIKE :t"), {"t": f"%sectest-{tag}%"})
    db.execute(text("DELETE FROM academy_verifications WHERE created_at >= :d AND (role IS NOT NULL OR purpose IN ('signup','login','password_reset'))"), {"d": datetime.utcnow() - timedelta(hours=1)})
    db.execute(text("DELETE FROM academy_account_security WHERE account_id NOT IN (SELECT client_id FROM clients) AND role='client'"))
    db.execute(text("DELETE FROM academy_account_security WHERE account_id NOT IN (SELECT us_id FROM users) AND role='admin'"))
    db.execute(text("DELETE FROM academy_account_security WHERE account_id NOT IN (SELECT vendor_id FROM vendors) AND role='apprenant'"))
    db.execute(text("DELETE FROM academy_trusted_devices WHERE (role='client' AND account_id NOT IN (SELECT client_id FROM clients)) OR (role='admin')"))
    db.execute(text("DELETE FROM academy_security_events WHERE created_at >= :d"), {"d": datetime.utcnow() - timedelta(hours=1)})
    if "made_type" in dir() and made_type:
        db.execute(text("DELETE FROM user_types WHERE ust_id=1"))
    db.commit()
    db.close()

print()
print(f"{len(fails)} echec(s) : {fails}" if fails else "Tous les controles passent. Donnees de test nettoyees.")
sys.exit(1 if fails else 0)
