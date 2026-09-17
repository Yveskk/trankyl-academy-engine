"""Envoi de SMS via AfrikSMS — memes identifiants que trankyl_backend_nodejs
(AFRIKSMS_API_KEY / AFRIKSMS_CLIENT_ID / AFRIKSMS_SENDER_ID), meme requete
HTTP GET que sa propre integration (pas de SDK officiel pour ce fournisseur)."""
import os
import re

import httpx


class SmsError(Exception):
    pass


def _normalize_phone(phone: str) -> str:
    """Retire le '+' et les espaces, comme trankyl_backend_nodejs."""
    return re.sub(r"[\s+]", "", phone)


def send_sms(phone: str, message: str) -> None:
    api_key = os.environ.get("AFRIKSMS_API_KEY")
    client_id = os.environ.get("AFRIKSMS_CLIENT_ID")
    sender_id = os.environ.get("AFRIKSMS_SENDER_ID")
    api_url = os.environ.get("AFRIKSMS_API_URL", "https://api.afriksms.com/api/web/web_v1/outbounds/send")

    if not api_key or not client_id or not sender_id:
        raise SmsError("Envoi de SMS non configure (variables AFRIKSMS manquantes).")

    try:
        response = httpx.get(
            api_url,
            params={
                "Message": message,
                "SenderId": sender_id,
                "MobileNumbers": _normalize_phone(phone),
                "ApiKey": api_key,
                "ClientId": client_id,
            },
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise SmsError(f"Echec de l'envoi du SMS : {e}") from e
