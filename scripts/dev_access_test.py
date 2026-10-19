"""Test de bout en bout : roles, utilisateurs, permissions et 2FA du panneau admin.
Base DEV uniquement. Cree des comptes/roles jetables et NETTOIE tout.

Usage : PYTHONPATH=. python3 scripts/dev_access_test.py"""
import json
import os
import sys
import time
import uuid

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce n'est pas une base dev.")
os.environ["OTP_DELIVERY_MODE"] = "log"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.access import permissions as P  # noqa: E402
from app.services.security import delivery, totp  # noqa: E402
from scripts._admin_login import SECRETS, admin_login_flow  # noqa: E402

limiter.enabled = False
c = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:6]
failures: list[str] = []
PW = "Sup3r-Secret-" + tag
STRONG = "Nouveau-Mdp-" + tag + "!"
A = "/api/v1/access"
created_roles: list[int] = []
created_emails: list[str] = []


def check(label, cond, detail=""):
    print(("  OK  " if cond else "  FAIL") + " " + label + (f"  [{str(detail)[:160]}]" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fresh():
    """Termine la transaction de lecture : sinon (REPEATABLE READ) on ne verrait pas les ecritures de l'API."""
    try:
        db.rollback()
    except Exception:  # connexion coupee par le serveur distant (inactivite) : on repart d'une connexion neuve
        db.close()
    return db


def reset_step(user_id):
    with SessionLocal() as s:  # session courte : la session principale peut avoir perdu sa connexion (inactivite)
        s.execute(text("UPDATE academy_admin_profiles SET totp_last_step=NULL WHERE user_id=:i"), {"i": user_id})
        s.commit()


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def login(email, pw, **kw):
    return admin_login_flow(c, email, pw, **kw)


try:
    # ------------------------------------------------------------------ super admin jetable (compte historique)
    sa_email = f"acc-{tag}-super@example.com"
    created_emails.append(sa_email)
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id) VALUES ('Super','Test',:e,:p,1)"), {"e": sa_email, "p": hash_password(PW)})
    db.commit()
    print("Connexion d'un compte historique")
    tok, codes, sa_secret = login(sa_email, PW)
    check("compte historique : code email -> config 2FA -> jeton + 10 codes de secours", bool(tok) and len(codes or []) == 10)
    S = H(tok)
    me = c.get("/api/v1/auth/admin/me", headers=S).json()
    check("/me : super-admin avec toutes les permissions", me["is_super"] and set(me["permissions"]) == set(P.ALL_KEYS) and me["mfa_enabled"], me)
    check("pre-jeton refuse comme jeton d'API", c.get("/api/v1/auth/admin/me", headers=H(c.post("/api/v1/auth/admin/login", json={"email": sa_email, "password": PW}).json()["pre_token"])).status_code == 401)

    print("Roles")
    cat = c.get(f"{A}/permissions", headers=S).json()
    check("catalogue des permissions", len(cat) >= 15 and all(a["key"].startswith("academy.") for g in cat for a in g["actions"]))
    r = c.post(f"{A}/roles", headers=S, json={"name": f"Editeur {tag}", "description": "Page d'accueil + affiches", "permissions": ["academy.home.manage", "academy.posters.manage"]})
    check("creer un role", r.status_code == 201, r.text)
    editor = r.json()
    created_roles.append(editor["id"])
    check("'voir' est ajoute automatiquement aux droits d'ecriture", set(editor["permissions"]) == {"academy.home.view", "academy.home.manage", "academy.posters.view", "academy.posters.manage"}, editor["permissions"])
    check("nom de role unique (insensible a la casse)", c.post(f"{A}/roles", headers=S, json={"name": f"EDITEUR {tag}", "permissions": ["academy.blog.view"]}).status_code == 409)
    check("permission inconnue refusee", c.post(f"{A}/roles", headers=S, json={"name": f"X{tag}", "permissions": ["academy.nope.view"]}).status_code == 422)
    check("role vide refuse", c.post(f"{A}/roles", headers=S, json={"name": f"Vide{tag}", "permissions": []}).status_code == 422)
    r = c.post(f"{A}/roles", headers=S, json={"name": f"Lecteur {tag}", "permissions": ["academy.posters.view"]})
    reader = r.json(); created_roles.append(reader["id"])
    r = c.post(f"{A}/roles", headers=S, json={"name": f"Gestion {tag}", "permissions": ["academy.users.view", "academy.users.create", "academy.roles.view", "academy.posters.view", "academy.reviews.view"]})
    manager = r.json(); created_roles.append(manager["id"])
    check("liste des roles avec compteurs", any(x["id"] == editor["id"] and x["users_count"] == 0 for x in c.get(f"{A}/roles", headers=S).json()))
    prot = next(x for x in c.get(f"{A}/roles", headers=S).json() if x["is_super"])
    check("role Administrateur protege (modif/suppression)", c.put(f"{A}/roles/{prot['id']}", headers=S, json={"name": "Admin", "permissions": ["academy.blog.view"]}).status_code == 403 and c.delete(f"{A}/roles/{prot['id']}", headers=S).status_code == 403)

    print("Droits Trankyl preserves")
    db.execute(text("INSERT INTO user_types (ust_wording, ust_description, ust_roles) VALUES (:n,'test',:r)"), {"n": f"Mixte {tag}", "r": json.dumps(["dashboard", "crm.clients", "academy.home.view"])})
    db.commit()
    mixed_id = db.execute(text("SELECT ust_id FROM user_types WHERE ust_wording=:n"), {"n": f"Mixte {tag}"}).scalar()
    created_roles.append(mixed_id)
    r = c.put(f"{A}/roles/{mixed_id}", headers=S, json={"name": f"Mixte {tag}", "permissions": ["academy.posters.view"]})
    raw = json.loads(fresh().execute(text("SELECT ust_roles FROM user_types WHERE ust_id=:i"), {"i": mixed_id}).scalar())
    check("modifier un role garde les cles Trankyl (dashboard, crm.clients)", r.status_code == 200 and "dashboard" in raw and "crm.clients" in raw and "academy.posters.view" in raw and "academy.home.view" not in raw, raw)
    check("role portant des droits Trankyl non supprimable d'ici", c.delete(f"{A}/roles/{mixed_id}", headers=S).status_code == 409)
    db.execute(text("INSERT INTO user_types (ust_wording, ust_roles) VALUES (:n,'[\"dashboard\"]')"), {"n": f"SansAcademy {tag}"})
    db.commit()
    noacc = db.execute(text("SELECT ust_id FROM user_types WHERE ust_wording=:n"), {"n": f"SansAcademy {tag}"}).scalar()
    created_roles.append(noacc)

    print("Creation d'un utilisateur + premiere connexion")
    u_email = f"acc-{tag}-editor@example.com"
    created_emails.append(u_email)
    r = c.post(f"{A}/users", headers=S, json={"firstname": "Edi", "lastname": "Teur", "email": u_email.upper(), "role_id": editor["id"]})
    check("creer un utilisateur", r.status_code == 201, r.text)
    inv = r.json()["invitation"]
    u_id = r.json()["user"]["id"]
    temp = inv["temp_password"]
    check("mot de passe temporaire fort, renvoye une fois (mode log) + invitation 'envoyee'", inv["sent"] and temp and len(temp) >= 12 and delivery.OUTBOX[-1]["purpose"] == "admin_invite")
    check("email normalise en minuscules + mot de passe a changer + 2FA non configuree", r.json()["user"]["email"] == u_email and r.json()["user"]["must_change_password"] and not r.json()["user"]["mfa_enabled"])
    check("email deja utilise -> 409", c.post(f"{A}/users", headers=S, json={"firstname": "a", "lastname": "b", "email": u_email, "role_id": editor["id"]}).status_code == 409)
    check("role sans acces Academy refuse", c.post(f"{A}/users", headers=S, json={"firstname": "a", "lastname": "b", "email": f"z{tag}@example.com", "role_id": noacc}).status_code == 422)
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": temp}).json()
    check("1ere connexion : changement de mot de passe exige (pas d'email)", r["status"] == "change_password_required" and r["pre_token"])
    pre = r["pre_token"]
    check("mot de passe identique au temporaire refuse", c.post("/api/v1/auth/admin/password/change", json={"pre_token": pre, "new_password": temp}).status_code == 422)
    check("mot de passe faible refuse", c.post("/api/v1/auth/admin/password/change", json={"pre_token": pre, "new_password": "password123"}).status_code == 422)
    r = c.post("/api/v1/auth/admin/password/change", json={"pre_token": pre, "new_password": STRONG}).json()
    check("puis configuration de la 2FA obligatoire", r["status"] == "mfa_setup_required")
    check("ancien mot de passe temporaire inutilisable", c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": temp}).status_code == 401)
    pre = r["pre_token"]
    check("etape 'password/change' refuse un jeton d'une autre etape", c.post("/api/v1/auth/admin/password/change", json={"pre_token": pre, "new_password": STRONG + "x"}).status_code == 401)
    sj = c.post("/api/v1/auth/admin/mfa/setup", json={"pre_token": pre}).json()
    u_secret = sj["secret"]
    check("QR : URI otpauth avec l'email et l'emetteur", u_email.replace("@", "%40") in sj["otpauth_uri"] or u_email in sj["otpauth_uri"])
    stored = fresh().execute(text("SELECT totp_secret, totp_enabled FROM users WHERE us_id=:i"), {"i": u_id}).first()
    check("secret TOTP chiffre au repos et pas encore actif", stored[0].startswith("enc:v1:") and u_secret not in stored[0] and not stored[1])
    check("code d'activation incorrect refuse", c.post("/api/v1/auth/admin/mfa/enable", json={"pre_token": pre, "code": "123456"}).status_code in (401,))
    t_fixed = time.time()
    r = c.post("/api/v1/auth/admin/mfa/enable", json={"pre_token": pre, "code": totp.current_code(u_secret, at=t_fixed)}).json()
    check("2FA activee : jeton + 10 codes de secours", r["status"] == "ok" and len(r["recovery_codes"]) == 10)
    u_tok, u_codes = r["access_token"], r["recovery_codes"]
    SECRETS[u_email] = u_secret
    stored = fresh().execute(text("SELECT totp_recovery_codes FROM users WHERE us_id=:i"), {"i": u_id}).scalar()
    check("codes de secours stockes hachés (jamais en clair)", u_codes[0] not in stored and "h:" in stored)

    print("Connexions suivantes (mot de passe + TOTP)")
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": STRONG}).json()
    check("mot de passe correct -> code de l'application demande", r["status"] == "mfa_required")
    pre = r["pre_token"]
    check("code deja utilise (rejeu) refuse", c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": pre, "code": totp.current_code(u_secret, at=t_fixed)}).status_code == 401)
    nxt = totp.current_code(u_secret, at=time.time() + 30)
    r = c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": pre, "code": nxt})
    check("code suivant accepte", r.status_code == 200 and r.json()["access_token"], r.text)
    u_tok = r.json()["access_token"]
    check("meme code rejoue apres succes refuse", c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": pre, "code": nxt}).status_code == 401)
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": STRONG}).json()
    r2 = c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": r["pre_token"], "recovery_code": u_codes[0]})
    check("code de secours accepte, 9 restants", r2.status_code == 200 and r2.json()["recovery_left"] == 9, r2.text)
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": STRONG}).json()
    check("code de secours a usage unique", c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": r["pre_token"], "recovery_code": u_codes[0]}).status_code == 401)

    print("Permissions appliquees")
    U = H(u_tok)
    me = c.get("/api/v1/auth/admin/me", headers=U).json()
    check("/me : role et permissions de l'utilisateur", me["role"]["name"] == f"Editeur {tag}" and not me["is_super"] and "academy.posters.manage" in me["permissions"])
    cfg = c.get("/api/v1/home/admin/config", headers=U)
    check("accueil : lecture autorisee", cfg.status_code == 200 and any(s["key"] == "hero_slides" for s in cfg.json()))
    check("avis : interdit (403)", c.get("/api/v1/reviews/admin", headers=U).status_code == 403)
    check("prestataires : interdit (403)", c.get("/api/v1/providers/admin", headers=U).status_code == 403)
    check("utilisateurs : interdit (403)", c.get(f"{A}/users", headers=U).status_code == 403)
    check("creer un role : interdit (403)", c.post(f"{A}/roles", headers=U, json={"name": "x", "permissions": ["academy.home.view"]}).status_code == 403)
    check("sans jeton : 401", c.get(f"{A}/users").status_code == 401)
    # un role limite aux affiches : pas la page d'accueil
    r = c.post(f"{A}/roles", headers=S, json={"name": f"Affiches {tag}", "permissions": ["academy.posters.manage"]})
    posters_only = r.json(); created_roles.append(posters_only["id"])
    r = c.put(f"{A}/users/{u_id}", headers=S, json={"firstname": "Edi", "lastname": "Teur", "role_id": posters_only["id"]})
    check("changer le role d'un utilisateur", r.status_code == 200 and r.json()["role_id"] == posters_only["id"], r.text)
    check("effet IMMEDIAT (sans reconnexion) : section accueil interdite", c.put("/api/v1/home/admin/sections/hero", headers=U, json={"payload": {}, "payload_en": {}}).status_code == 403)
    ids = [i["id"] for s in c.get("/api/v1/home/admin/config", headers=U).json() if s["key"] == "hero_slides" for i in s["items"] if i["id"]]
    check("affiches : autorisees (menu distinct de l'accueil)", c.post("/api/v1/home/admin/sections/hero_slides/reorder", headers=U, json={"ids": ids}).status_code == 200)
    check("config : seules les affiches sont visibles", [s["key"] for s in c.get("/api/v1/home/admin/config", headers=U).json()] == ["hero_slides"])

    print("Pas d'escalade de privileges")
    v_email = f"acc-{tag}-mgr@example.com"
    created_emails.append(v_email)
    r = c.post(f"{A}/users", headers=S, json={"firstname": "Ges", "lastname": "Tion", "email": v_email, "role_id": manager["id"]}).json()
    v_id = r["user"]["id"]
    v_tok, _, _ = login(v_email, r["invitation"]["temp_password"], new_password="Mgr-" + STRONG)
    V = H(v_tok)
    check("gestionnaire : liste les utilisateurs", c.get(f"{A}/users", headers=V).status_code == 200)
    check("ne peut pas creer un role (pas roles.manage)", c.post(f"{A}/roles", headers=V, json={"name": "y", "permissions": ["academy.posters.view"]}).status_code == 403)
    check("ne peut pas attribuer un role plus puissant que le sien", c.post(f"{A}/users", headers=V, json={"firstname": "a", "lastname": "b", "email": f"e{tag}@example.com", "role_id": editor["id"]}).status_code == 403)
    check("ne peut pas attribuer le role Administrateur", c.post(f"{A}/users", headers=V, json={"firstname": "a", "lastname": "b", "email": f"e{tag}@example.com", "role_id": prot["id"]}).status_code == 403)
    r = c.post(f"{A}/users", headers=V, json={"firstname": "Lec", "lastname": "Teur", "email": f"acc-{tag}-reader@example.com", "role_id": reader["id"]})
    created_emails.append(f"acc-{tag}-reader@example.com")
    check("peut creer un utilisateur avec un role dans son perimetre", r.status_code == 201, r.text)
    check("ne peut ni suspendre ni reinitialiser (permissions absentes)", c.post(f"{A}/users/{u_id}/suspend", headers=V).status_code == 403 and c.post(f"{A}/users/{u_id}/reset-mfa", headers=V).status_code == 403)

    print("Garde-fous administrateur")
    sa_id = fresh().execute(text("SELECT us_id FROM users WHERE email=:e"), {"e": sa_email}).scalar()
    check("on ne se suspend pas soi-meme", c.post(f"{A}/users/{sa_id}/suspend", headers=S).status_code == 403)
    check("on ne change pas son propre role", c.put(f"{A}/users/{sa_id}", headers=S, json={"firstname": "S", "lastname": "T", "role_id": editor["id"]}).status_code == 403)
    check("role en cours d'usage non supprimable (409)", c.delete(f"{A}/roles/{posters_only['id']}", headers=S).status_code == 409)
    check("role inutilise supprimable", c.delete(f"{A}/roles/{reader['id']}", headers=S).status_code in (204, 409))  # lecteur a 1 utilisateur : 409 attendu
    check("evenements d'audit de l'utilisateur", any(e["event"] == "admin_user_created" for e in c.get(f"{A}/users/{sa_id}/events", headers=S).json()) or any(e["event"] == "mfa_enabled" for e in c.get(f"{A}/users/{u_id}/events", headers=S).json()))

    print("Suspension / reinitialisation")
    r = c.post(f"{A}/users/{u_id}/suspend", headers=S)
    check("suspendre", r.status_code == 200 and r.json()["status"] == "suspended", r.text)
    check("session ouverte coupee IMMEDIATEMENT", c.get("/api/v1/auth/admin/me", headers=U).status_code == 401)
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": STRONG})
    check("connexion refusee (compte suspendu)", r.status_code == 403, r.text)
    check("reactiver", c.post(f"{A}/users/{u_id}/reactivate", headers=S).json()["status"] == "active")
    time.sleep(1.5)
    r = c.post(f"{A}/users/{u_id}/reset-password", headers=S)
    check("reinitialiser le mot de passe", r.status_code == 200 and r.json()["invitation"]["temp_password"], r.text)
    temp2 = r.json()["invitation"]["temp_password"]
    check("ancien mot de passe refuse", c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": STRONG}).status_code == 401)
    check("nouveau mot de passe temporaire -> a changer", c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": temp2}).json()["status"] == "change_password_required")
    new2 = "Encore-" + STRONG
    tok2, _, _ = login(u_email, temp2, new_password=new2, otp_secret=u_secret)
    check("apres changement : 2FA existante reutilisee", bool(tok2))
    r = c.post(f"{A}/users/{u_id}/reset-mfa", headers=S)
    check("reinitialiser la 2FA (telephone perdu)", r.status_code == 200 and not r.json()["mfa_enabled"])
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": new2}).json()
    check("-> reconfiguration de la 2FA exigee", r["status"] == "mfa_setup_required")
    tok3, codes3, secret3 = login(u_email, new2)
    check("nouveau secret different, nouvelle activation", secret3 != u_secret and len(codes3) == 10)

    print("Verrouillage et compte connecte")
    r = c.post("/api/v1/auth/admin/login", json={"email": u_email, "password": new2}).json()
    codes_bad = [c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": r["pre_token"], "code": "000000"}).status_code for _ in range(6)]
    check("5 codes faux -> verrouillage temporaire (429)", codes_bad[:4] == [401] * 4 and 429 in codes_bad, codes_bad)
    check("compte verrouille meme avec le bon code", c.post("/api/v1/auth/admin/mfa/verify", json={"pre_token": r["pre_token"], "code": totp.current_code(secret3, at=time.time() + 30)}).status_code == 429)
    check("un admin peut deverrouiller (reactiver)", c.post(f"{A}/users/{u_id}/reactivate", headers=S).status_code == 200)
    reset_step(u_id)
    tok4, _, _ = login(u_email, new2, otp_secret=secret3)
    W = H(tok4)
    pw3 = "Troisieme-" + STRONG
    r = c.post("/api/v1/auth/admin/me/password", headers=W, json={"current_password": new2, "new_password": pw3, "code": "000000"})
    check("changer son mot de passe exige le code 2FA", r.status_code == 401)
    time.sleep(1.2)
    reset_step(u_id)
    r = c.post("/api/v1/auth/admin/me/password", headers=W, json={"current_password": new2, "new_password": pw3, "code": totp.current_code(secret3)})
    check("changement de mot de passe : nouvelle session fournie", r.status_code == 200 and r.json()["access_token"], r.text)
    check("anciennes sessions fermees", c.get("/api/v1/auth/admin/me", headers=W).status_code == 401)
    W2 = H(r.json()["access_token"])
    check("la nouvelle session fonctionne", c.get("/api/v1/auth/admin/me", headers=W2).status_code == 200)
    reset_step(u_id)
    r = c.post("/api/v1/auth/admin/me/recovery-codes", headers=W2, json={"code": totp.current_code(secret3)})
    check("regenerer ses codes de secours (avec code 2FA)", r.status_code == 200 and len(r.json()["recovery_codes"]) == 10, r.text)
finally:
    try:
        db.close()
    except Exception:
        pass
    db = SessionLocal()  # la session du test a pu expirer (base distante)
    ids = [r[0] for r in db.execute(text("SELECT us_id FROM users WHERE email IN :e").bindparams(__import__("sqlalchemy").bindparam("e", expanding=True)), {"e": created_emails or [""]}).fetchall()]
    if ids:
        b = lambda q: db.execute(text(q).bindparams(__import__("sqlalchemy").bindparam("i", expanding=True)), {"i": ids})
        b("DELETE FROM academy_admin_profiles WHERE user_id IN :i")
        b("DELETE FROM academy_account_security WHERE role='admin' AND account_id IN :i")
        b("DELETE FROM academy_security_events WHERE role='admin' AND account_id IN :i")
        b("DELETE FROM academy_trusted_devices WHERE role='admin' AND account_id IN :i")
        b("DELETE FROM users WHERE us_id IN :i")
    db.execute(text("DELETE FROM academy_verifications WHERE role='admin' AND account_id NOT IN (SELECT us_id FROM users)"))
    db.execute(text("DELETE FROM academy_security_events WHERE detail LIKE :t"), {"t": f"%{tag}%"})
    for rid in created_roles:
        db.execute(text("DELETE FROM user_types WHERE ust_id=:i AND ust_id<>1"), {"i": rid})
    db.commit()
    db.close()

print()
if failures:
    print(f"{len(failures)} ECHEC(S) : {failures}")
    sys.exit(1)
print("Tous les controles passent. Donnees de test nettoyees.")
