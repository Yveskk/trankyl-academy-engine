"""Envoi des codes : WhatsApp (Cloud API, modele Meta approuve), SMS (AfrikSMS),
email (Mailjet) — memes identifiants que trankyl_backend_nodejs.

`OTP_DELIVERY_MODE=log` (defaut) : AUCUN message n'est envoye ; le code est
ecrit dans la console du serveur (et garde en memoire pour les tests). Il ne
sort jamais dans une reponse d'API."""
import logging
import re
from collections import deque

import httpx

from app.core.config import settings
from app.services.mail import MailError, send_email
from app.services.sms import SmsError, send_sms

_log = logging.getLogger("otp")

# Boite d'envoi en memoire (mode "log" uniquement), pour les tests automatises.
OUTBOX: deque[dict] = deque(maxlen=200)


class DeliveryError(Exception):
    def __init__(self, channel: str, message: str):
        super().__init__(message)
        self.channel = channel


def mask_destination(channel: str, destination: str) -> str:
    """"+228 ******00" / "y***@trankyl.com" : assez pour reconnaitre sa cible, pas pour la reveler."""
    if channel == "email" or "@" in destination:
        local, _, domain = destination.partition("@")
        return f"{local[:1]}***@{domain}" if domain else "***"
    digits = destination.lstrip("+")
    m = re.match(r"^(\d{1,3}?)(\d+)$", digits)
    for code in ("228", "229", "225", "223", "237", "33", "1"):
        if digits.startswith(code) and len(digits) > len(code) + 2:
            return f"+{code} {'*' * (len(digits) - len(code) - 2)}{digits[-2:]}"
    return f"+{digits[:2]} {'*' * max(0, len(digits) - 4)}{digits[-2:]}" if m else "***"


def _whatsapp_number(destination: str) -> str:
    return destination.lstrip("+").replace(" ", "")


def _send_whatsapp(destination: str, code: str, lang: str) -> None:
    token = (settings.whatsapp_token or "").strip()
    phone_id = (settings.whatsapp_phone_id or "").strip()
    if not token or not phone_id:
        raise DeliveryError("whatsapp", "WhatsApp n'est pas configure sur le serveur.")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _whatsapp_number(destination),
        "type": "template",
        "template": {
            "name": settings.whatsapp_otp_template,
            "language": {"code": "fr"},  # le modele approuve est en francais
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]},
            ],
        },
    }
    try:
        r = httpx.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except httpx.HTTPError as e:
        raise DeliveryError("whatsapp", "WhatsApp est momentanement indisponible.") from e
    if r.status_code >= 400:
        # Jamais le jeton ni le code dans les journaux : seulement le motif renvoye par Meta.
        reason = ""
        try:
            reason = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            pass
        _log.warning("WhatsApp OTP refuse (HTTP %s) : %s", r.status_code, reason[:200])
        raise DeliveryError("whatsapp", "Le message WhatsApp n'a pas pu etre envoye.")


def _sms_text(code: str, lang: str) -> str:
    minutes = settings.otp_ttl_minutes
    if lang == "en":
        return f"TRANKYL: Your verification code is {code}. Valid for {minutes} min. Never share it with anyone."
    return f"TRANKYL: Votre code de verification est {code}. Valable {minutes} min. Ne le partagez jamais."


def _email_content(code: str, lang: str, purpose: str) -> tuple[str, str]:
    minutes = settings.otp_ttl_minutes
    if lang == "en":
        subject = f"{code} is your Trankyl verification code"
        title, intro = "Your verification code", f"Enter this code to continue. It is valid for {minutes} minutes."
        warn = "If you did not request this code, ignore this email and do not share it with anyone. Trankyl will never ask you for it."
    else:
        subject = f"{code} est votre code de verification Trankyl"
        title, intro = "Votre code de vérification", f"Saisissez ce code pour continuer. Il est valable {minutes} minutes."
        warn = "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email et ne communiquez ce code à personne. Trankyl ne vous le demandera jamais."
    html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px;color:#1b2620">
  <h2 style="margin:0 0 8px">{title}</h2><p style="margin:0 0 20px;color:#46524b">{intro}</p>
  <div style="font-size:34px;letter-spacing:10px;font-weight:700;background:#fff4d1;border-radius:12px;padding:16px;text-align:center">{code}</div>
  <p style="margin:20px 0 0;font-size:12px;color:#6b7280">{warn}</p></div>"""
    return subject, html


def send_code(channel: str, destination: str, code: str, *, lang: str = "fr", purpose: str = "login") -> None:
    if settings.otp_delivery_mode != "live":
        # Mode developpement : rien ne part. Le code n'est ecrit que dans la console du serveur.
        _log.warning("[OTP:%s] %s -> %s : %s (mode log, aucun envoi)", purpose, channel, mask_destination(channel, destination), code)
        OUTBOX.append({"channel": channel, "destination": destination, "code": code, "purpose": purpose, "lang": lang})
        return
    try:
        if channel == "whatsapp":
            _send_whatsapp(destination, code, lang)
        elif channel == "sms":
            send_sms(destination, _sms_text(code, lang))
        elif channel == "email":
            subject, html = _email_content(code, lang, purpose)
            send_email(destination, subject, html)
        else:
            raise DeliveryError(channel, "Canal inconnu.")
    except SmsError as e:
        raise DeliveryError("sms", "Le SMS n'a pas pu etre envoye.") from e
    except MailError as e:
        raise DeliveryError("email", "L'email n'a pas pu etre envoye.") from e


def send_admin_invitation(email: str, firstname: str, temp_password: str, login_url: str, role_name: str, *, reset: bool = False) -> None:
    """Invitation (ou reinitialisation) d'un compte du panneau admin : mot de passe TEMPORAIRE a changer
    a la premiere connexion (qui impose aussi la configuration de la 2FA). Mode "log" : rien n'est envoye."""
    if settings.otp_delivery_mode != "live":
        _log.warning("[ADMIN_INVITE] email -> %s (role %s, mode log, aucun envoi)", mask_destination("email", email), role_name)
        OUTBOX.append({"channel": "email", "destination": email, "code": temp_password, "purpose": "admin_invite", "lang": "fr"})
        return
    title = "Votre accès a été réinitialisé" if reset else "Bienvenue dans l'administration Trankyl Academy"
    intro = "Un administrateur a réinitialisé votre mot de passe." if reset else f"Un compte vous a été créé avec le rôle <b>{role_name}</b>."
    html = f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:24px;color:#1b2620">
  <h2 style="margin:0 0 8px">{title}</h2>
  <p style="color:#46524b">Bonjour {firstname}, {intro}</p>
  <p style="margin:16px 0 6px;color:#46524b">Mot de passe temporaire :</p>
  <div style="font-size:22px;font-family:monospace;font-weight:700;background:#fff4d1;border-radius:12px;padding:14px;text-align:center">{temp_password}</div>
  <ol style="color:#46524b;line-height:1.7">
    <li>Connectez-vous sur <a href="{login_url}">{login_url}</a></li>
    <li>Choisissez votre propre mot de passe</li>
    <li>Configurez la double authentification avec une application (Google Authenticator, Microsoft Authenticator, Authy…)</li>
  </ol>
  <p style="font-size:12px;color:#6b7280">Ce mot de passe ne fonctionne qu'une fois et doit être changé immédiatement. Si vous n'attendiez pas ce message, ignorez-le et prévenez un administrateur. Personne ne vous demandera jamais ce mot de passe.</p></div>"""
    try:
        send_email(email, "Votre accès à l'administration Trankyl Academy", html)
    except MailError as e:
        raise DeliveryError("email", "L'email d'invitation n'a pas pu etre envoye.") from e
