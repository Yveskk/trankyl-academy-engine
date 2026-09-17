"""Envoi d'email via Mailjet — memes identifiants que trankyl_backend_nodejs
(MAILJET_API_KEY / MAILJET_SECRET_KEY / SENDER_EMAIL), appele directement en
REST (comme le fait sa propre integration, qui n'utilise pas non plus le SDK
officiel node-mailjet pour la partie HTTP)."""
import os

import httpx


class MailError(Exception):
    pass


def send_email(to_email: str, subject: str, html_body: str) -> None:
    api_key = os.environ.get("MAILJET_API_KEY")
    secret_key = os.environ.get("MAILJET_SECRET_KEY")
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_name = os.environ.get("MAILJET_FROM_NAME", "Trankyl")

    if not api_key or not secret_key or not sender_email:
        raise MailError("Envoi d'email non configure (variables MAILJET/SENDER_EMAIL manquantes).")

    payload = {
        "Messages": [
            {
                "From": {"Email": sender_email, "Name": sender_name},
                "To": [{"Email": to_email}],
                "Subject": subject,
                "HTMLPart": html_body,
            }
        ]
    }

    try:
        response = httpx.post(
            "https://api.mailjet.com/v3.1/send",
            json=payload,
            auth=(api_key, secret_key),
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise MailError(f"Echec de l'envoi de l'email : {e}") from e
