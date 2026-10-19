"""E-mails des demandes de devis : alerte a l'administration (nouvelle demande) et reponse au demandeur.

Meme habillage que les e-mails de reservation (`booking_mail`). Tout texte saisi est echappe. Mode
`OTP_DELIVERY_MODE=log` : rien ne part, le message est garde en memoire (`delivery.OUTBOX`)."""
from __future__ import annotations

import logging
from html import escape

from app.core.config import settings
from app.services.booking_mail import GOLD, GREEN, INK, MUTED, _layout, _row
from app.services.mail import MailError, send_email
from app.services.security import delivery

_log = logging.getLogger("quote-mail")


def _multiline(text: str) -> str:
    return escape(text).replace("\n", "<br>")


def render_admin(q: dict) -> tuple[str, str]:
    """Alerte interne (en francais) : une nouvelle demande de devis vient d'arriver."""
    base = settings.admin_panel_url.replace("/admin/login", "").rstrip("/")
    rows = _row("Prestataire", escape(q["vendor_name"] or f'#{q["vendor_id"]}'))
    rows += _row("Demandeur", escape(q["name"]) + (' <span style="color:%s;font-weight:500">(compte client)</span>' % MUTED if q.get("client_id") else ""))
    rows += _row("E-mail", f'<a href="mailto:{escape(q["email"], quote=True)}" style="color:{GREEN}">{escape(q["email"])}</a>')
    if q.get("phone"):
        rows += _row("Téléphone", escape(q["phone"]))
    if q.get("slot_label"):
        rows += _row("Créneau souhaité", escape(q["slot_label"]))
    rows += _row("Pays", escape(q["country_code"]))
    extra = (
        f'<div style="background:#fbf8ee;border:1px solid #e9e5d8;border-radius:14px;padding:14px 18px">'
        f'<p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};font-weight:700">Besoin décrit</p>'
        f'<p style="margin:0;font-size:14px;line-height:1.6;color:{INK}">{_multiline(q["message"])}</p></div>'
    )
    html = _layout(
        title="Nouvelle demande de devis", preheader=f'{q["name"]} demande un devis à {q["vendor_name"] or "un prestataire"}.', hello=None,
        intro="Une demande de devis vient d'être envoyée depuis Trankyl Academy. Vous pouvez y répondre depuis l'administration.", rows=rows, price_html="", extra_html=extra,
        cta_label="Répondre au devis", cta_url=f"{base}/admin/devis", foot="Trankyl Academy — des prestataires vérifiés, près de chez vous.", foot2="Alerte interne : nouvelle demande de devis.", ref=f'Devis #{q["id"]}',
    )
    return f'Nouvelle demande de devis — {q["vendor_name"] or "prestataire"} ({q["name"]})', html


def render_reply(q: dict, subject: str, message: str) -> tuple[str, str]:
    """Reponse de l'administration au demandeur, dans sa langue."""
    en = q.get("lang") == "en"
    first = (q["name"] or "").split(" ")[0]
    rows = _row("Prestataire" if not en else "Provider", escape(q["vendor_name"] or "—"))
    extra = (
        f'<div style="background:#fbf8ee;border:1px solid #e9e5d8;border-radius:14px;padding:14px 18px;margin-bottom:12px">'
        f'<p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};font-weight:700">{"Our answer" if en else "Notre réponse"}</p>'
        f'<p style="margin:0;font-size:15px;line-height:1.65;color:{INK}">{_multiline(message)}</p></div>'
        f'<p style="margin:0;font-size:12px;color:{MUTED};line-height:1.5"><strong>{"Your request" if en else "Votre demande"} :</strong><br>{_multiline(q["message"])}</p>'
    )
    html = _layout(
        title=subject, preheader=message[:90], hello=(f"Hello {first}," if en else f"Bonjour {first},") if first else None,
        intro="Here is the answer to your quote request." if en else "Voici la réponse à votre demande de devis.", rows=rows, price_html="", extra_html=extra,
        cta_label="Browse providers" if en else "Voir les prestataires", cta_url=f'{settings.public_site_url.rstrip("/")}/recherche',
        foot="Trankyl Academy — verified providers, close to you." if en else "Trankyl Academy — des prestataires vérifiés, près de chez vous.",
        foot2="You receive this email because you asked for a quote on Trankyl Academy." if en else "Vous recevez cet e-mail car vous avez demandé un devis sur Trankyl Academy.", ref=f'Devis #{q["id"]}' if not en else f'Quote #{q["id"]}',
    )
    return subject, html


def deliver(to: str, subject: str, html: str, purpose: str, *, strict: bool = False) -> None:
    """Envoie l'e-mail. `strict` : propage l'echec (la reponse admin doit signaler un e-mail non parti) ; sinon il est seulement journalise."""
    if settings.otp_delivery_mode != "live":
        _log.warning("[QUOTE_MAIL:%s] -> %s (mode log, aucun envoi)", purpose, delivery.mask_destination("email", to))
        delivery.OUTBOX.append({"channel": "email", "destination": to, "code": None, "purpose": purpose, "lang": "fr", "subject": subject, "html": html})
        return
    try:
        send_email(to, subject, html)
    except MailError as e:
        _log.error("E-mail de devis (%s) non envoye : %s", purpose, e)
        if strict:
            raise


def notify_admins_new_quote(q: dict) -> None:
    """Arriere-plan : ne leve jamais d'exception (la demande est deja enregistree)."""
    try:
        admins = settings.admin_email_list
        if not admins:
            _log.warning("ADMIN_EMAIL non configure : alerte du devis #%s non envoyee.", q.get("id"))
            return
        subject, html = render_admin(q)
        for to in admins:
            deliver(to, subject, html, "quote_admin")
    except Exception:  # noqa: BLE001
        _log.exception("Notification du devis #%s en echec", q.get("id"))
