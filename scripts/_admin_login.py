"""Connexion admin complete pour les scripts de test (dev uniquement) : gere toutes les etapes
(code email d'un compte historique, changement du mot de passe temporaire, configuration de la 2FA,
code TOTP). Le secret TOTP est lu depuis la reponse de /mfa/setup : en test on joue le role de
l'application d'authentification."""
import time

from app.services.security import delivery, totp

SECRETS: dict[str, str] = {}  # email -> secret TOTP (une fois la 2FA configuree)


def admin_login_flow(client, email, password, *, new_password=None, otp_secret=None):
    """Retourne (access_token, recovery_codes|None, secret)."""
    base = "/api/v1/auth"
    secret = otp_secret or SECRETS.get(email)
    r = client.post(f"{base}/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    r = r.json()
    codes = None
    if r["status"] == "verification_required":  # compte historique : preuve de la boite email
        r = client.post(f"{base}/login/verify", json={"request_id": r["request_id"], "code": delivery.OUTBOX[-1]["code"]})
        assert r.status_code == 200, r.text
        r = r.json()
    if r["status"] == "change_password_required":
        assert new_password, "mot de passe temporaire : new_password requis"
        r = client.post(f"{base}/admin/password/change", json={"pre_token": r["pre_token"], "new_password": new_password})
        assert r.status_code == 200, r.text
        r = r.json()
    if r["status"] == "mfa_setup_required":
        setup = client.post(f"{base}/admin/mfa/setup", json={"pre_token": r["pre_token"]})
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        r = client.post(f"{base}/admin/mfa/enable", json={"pre_token": r["pre_token"], "code": totp.current_code(secret)})
        assert r.status_code == 200, r.text
        r = r.json()
        codes = r.get("recovery_codes")
    elif r["status"] == "mfa_required":
        assert secret, "2FA deja configuree : secret TOTP requis"
        pre = r["pre_token"]
        r = client.post(f"{base}/admin/mfa/verify", json={"pre_token": pre, "code": totp.current_code(secret)})
        if r.status_code == 401:  # meme periode de 30 s que le code precedent (anti-rejeu) : on attend la suivante
            time.sleep(totp.PERIOD - time.time() % totp.PERIOD + 0.5)
            r = client.post(f"{base}/admin/mfa/verify", json={"pre_token": pre, "code": totp.current_code(secret)})
        assert r.status_code == 200, r.text
        r = r.json()
    assert r["status"] == "ok", r
    SECRETS[email] = secret
    return r["access_token"], codes, secret


def admin_token(client, email, password):
    return admin_login_flow(client, email, password)[0]
