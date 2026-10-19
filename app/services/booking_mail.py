"""E-mails de reservation : confirmation au client et alerte a l'administration, avec un modele HTML soigne.

- Le HTML est "email-safe" : tableaux, styles en ligne, largeur 600 px, sans image externe obligatoire.
- Tout est echappe (`html.escape`) : aucun texte saisi par un client n'est injecte tel quel dans le HTML.
- Envoi en arriere-plan : un echec d'envoi ne bloque JAMAIS la reservation.
- Mode `OTP_DELIVERY_MODE=log` (developpement) : rien ne part, le message est garde en memoire (`delivery.OUTBOX`).
- Si la reservation est confiee au backend Trankyl (`NODE_API_URL`), c'est lui qui envoie ses propres e-mails : on n'en
  envoie pas de doublon."""
from __future__ import annotations

import logging
from datetime import date
from html import escape

from app.core.config import settings
from app.services.mail import MailError, send_email
from app.services.security import delivery

_log = logging.getLogger("booking-mail")

GOLD, GREEN, INK, MUTED, LINE, CREAM = "#ffc72c", "#04330d", "#14211a", "#66706a", "#e9e5d8", "#fbf8ee"

_T = {
    "fr": {
        "client_subject": "Votre réservation {ref} est enregistrée",
        "client_pre": "Nous avons bien reçu votre demande de réservation.",
        "client_title": "Réservation enregistrée",
        "client_hello": "Bonjour {name},",
        "client_intro": "Merci de votre confiance. {vendor} a bien reçu votre demande et vous contactera pour confirmer le rendez-vous.",
        "admin_subject": "Nouvelle réservation {ref} — {service}",
        "admin_pre": "Une nouvelle réservation vient d'être enregistrée.",
        "admin_title": "Nouvelle réservation",
        "admin_intro": "Une réservation vient d'être effectuée depuis Trankyl Academy.",
        "ref": "Référence", "service": "Service", "provider": "Prestataire", "when": "Rendez-vous", "where": "Adresse", "district": "Quartier",
        "map": "Position", "info": "Informations", "payment": "Paiement", "client": "Client", "phone": "Téléphone", "email": "Email", "country": "Pays",
        "options": "Options", "qty": "Quantité", "coupon": "Code promo",
        "cash": "En espèces, à la fin de la prestation", "online": "En ligne",
        "price": "Détail du prix", "p_service": "Service", "p_options": "Options", "p_linking": "Mise en relation", "p_discount": "Réduction", "p_total": "Total",
        "next": "Et maintenant ?", "next1": "Le prestataire vous contacte pour confirmer l'horaire.", "next2": "Vous suivez et pouvez annuler votre réservation depuis votre espace.", "next3": "Le règlement se fait comme indiqué ci-dessus.",
        "cta_client": "Voir ma réservation", "cta_admin": "Ouvrir dans l'administration", "open_map": "Ouvrir sur la carte",
        "foot": "Trankyl Academy — des prestataires vérifiés, près de chez vous.", "foot2": "Vous recevez cet e-mail car une réservation a été faite avec cette adresse.",
        "none": "—",
    },
    "en": {
        "client_subject": "Your booking {ref} is confirmed",
        "client_pre": "We have received your booking request.",
        "client_title": "Booking received",
        "client_hello": "Hello {name},",
        "client_intro": "Thank you for your trust. {vendor} has received your request and will contact you to confirm the appointment.",
        "admin_subject": "New booking {ref} — {service}",
        "admin_pre": "A new booking has just been made.",
        "admin_title": "New booking",
        "admin_intro": "A booking has just been made on Trankyl Academy.",
        "ref": "Reference", "service": "Service", "provider": "Provider", "when": "Appointment", "where": "Address", "district": "District",
        "map": "Location", "info": "Notes", "payment": "Payment", "client": "Customer", "phone": "Phone", "email": "Email", "country": "Country",
        "options": "Options", "qty": "Quantity", "coupon": "Promo code",
        "cash": "Cash, at the end of the service", "online": "Online",
        "price": "Price breakdown", "p_service": "Service", "p_options": "Options", "p_linking": "Connection fee", "p_discount": "Discount", "p_total": "Total",
        "next": "What happens next?", "next1": "The provider contacts you to confirm the time.", "next2": "You can follow and cancel your booking from your account.", "next3": "Payment is made as indicated above.",
        "cta_client": "View my booking", "cta_admin": "Open in the admin", "open_map": "Open on the map",
        "foot": "Trankyl Academy — verified providers, close to you.", "foot2": "You receive this email because a booking was made with this address.",
        "none": "—",
    },
}


def _e(v) -> str:
    return escape(str(v if v not in (None, "") else "—"))


def _fcfa(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ") + " FCFA"


def _when(d: str, hhmm: str, lang: str) -> str:
    try:
        day = date.fromisoformat(d)
        names_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        months_fr = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        names_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        months_en = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        if lang == "en":
            return f"{names_en[day.weekday()]}, {day.day} {months_en[day.month - 1]} {day.year} · {hhmm}"
        return f"{names_fr[day.weekday()].capitalize()} {day.day} {months_fr[day.month - 1]} {day.year} à {hhmm}"
    except ValueError:
        return f"{d} {hhmm}"


def _row(label: str, value_html: str) -> str:
    return (
        f'<tr><td style="padding:9px 0;border-bottom:1px solid {LINE};color:{MUTED};font-size:13px;width:38%;vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid {LINE};color:{INK};font-size:14px;font-weight:600;vertical-align:top">{value_html}</td></tr>'
    )


def _layout(*, title: str, preheader: str, hello: str | None, intro: str, rows: str, price_html: str, extra_html: str, cta_label: str, cta_url: str, foot: str, foot2: str, ref: str) -> str:
    hello_html = f'<p style="margin:0 0 6px;font-size:16px;font-weight:700;color:{INK}">{escape(hello)}</p>' if hello else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{CREAM};font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{escape(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CREAM};padding:24px 12px"><tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:20px;overflow:hidden;border:1px solid {LINE}">
    <tr><td style="background:{GREEN};padding:22px 28px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td style="font-size:20px;font-weight:800;color:#ffffff;letter-spacing:.2px">Trankyl <span style="color:{GOLD}">Academy</span></td>
        <td align="right" style="font-size:12px;color:#cfe3d4">{escape(ref)}</td>
      </tr></table>
    </td></tr>
    <tr><td style="background:{GOLD};height:5px;line-height:5px;font-size:0">&nbsp;</td></tr>
    <tr><td style="padding:30px 28px 8px">
      <h1 style="margin:0 0 14px;font-size:24px;line-height:1.25;color:{INK}">{escape(title)}</h1>
      {hello_html}
      <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#3d4842">{escape(intro)}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 6px">{rows}</table>
    </td></tr>
    <tr><td style="padding:12px 28px 4px">{price_html}</td></tr>
    <tr><td style="padding:8px 28px 0">{extra_html}</td></tr>
    <tr><td align="center" style="padding:24px 28px 30px">
      <a href="{escape(cta_url, quote=True)}" style="display:inline-block;background:{GOLD};color:{GREEN};font-weight:800;font-size:15px;text-decoration:none;padding:14px 28px;border-radius:12px">{escape(cta_label)}</a>
    </td></tr>
    <tr><td style="background:{CREAM};padding:18px 28px;border-top:1px solid {LINE}">
      <p style="margin:0 0 4px;font-size:12px;color:{INK};font-weight:700">{escape(foot)}</p>
      <p style="margin:0;font-size:11px;color:{MUTED};line-height:1.5">{escape(foot2)}</p>
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def _price_block(t: dict, price: dict) -> str:
    def line(label: str, value: str, strong: bool = False, color: str = INK) -> str:
        w = "800" if strong else "600"
        size = "16px" if strong else "14px"
        border = f"border-top:2px solid {INK};" if strong else ""
        return f'<tr><td style="padding:8px 0;{border}color:{color if not strong else INK};font-size:{size};font-weight:{w}">{escape(label)}</td><td align="right" style="padding:8px 0;{border}color:{color if not strong else INK};font-size:{size};font-weight:{w}">{value}</td></tr>'

    rows = line(t["p_service"], _fcfa(price["service"]))
    if price.get("options"):
        rows += line(t["p_options"], _fcfa(price["options"]))
    rows += line(t["p_linking"], _fcfa(price["linking"]))
    if price.get("discount"):
        rows += line(t["p_discount"], "− " + _fcfa(price["discount"]), color="#127a3a")
    rows += line(t["p_total"], _fcfa(price["total"]), strong=True)
    return (
        f'<div style="background:{CREAM};border:1px solid {LINE};border-radius:14px;padding:14px 18px">'
        f'<p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};font-weight:700">{escape(t["price"])}</p>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></div>'
    )


def _details_rows(t: dict, ctx: dict, *, admin: bool) -> str:
    lang = ctx["lang"]
    pay = t["cash"] if ctx["payment"] == "cash" else t["online"]
    rows = _row(t["ref"], f'<span style="letter-spacing:.08em">{_e(ctx["ref"])}</span>')
    rows += _row(t["service"], _e(ctx["service"]) + (f' <span style="color:{MUTED};font-weight:500">× {int(ctx["qty"])}</span>' if int(ctx["qty"]) > 1 else ""))
    if ctx.get("options"):
        rows += _row(t["options"], _e(", ".join(o["name"] for o in ctx["options"])))
    rows += _row(t["provider"], _e(ctx["vendor_name"]) + (f'<br><span style="color:{MUTED};font-weight:500">{_e(ctx.get("vendor_phone"))}</span>' if admin and ctx.get("vendor_phone") else ""))
    rows += _row(t["when"], escape(_when(ctx["date"], ctx["time"], lang)))
    rows += _row(t["where"], _e(ctx["address"]))
    if ctx.get("district"):
        rows += _row(t["district"], _e(ctx["district"]))
    if ctx.get("map_link"):
        rows += _row(t["map"], f'<a href="{escape(ctx["map_link"], quote=True)}" style="color:{GREEN}">{escape(t["open_map"])}</a>')
    if ctx.get("info"):
        rows += _row(t["info"], _e(ctx["info"]))
    rows += _row(t["payment"], escape(pay))
    if ctx.get("coupon"):
        rows += _row(t["coupon"], _e(ctx["coupon"]))
    if admin:
        rows += _row(t["client"], _e(ctx["client_name"]))
        rows += _row(t["phone"], _e(ctx["client_phone"]))
        rows += _row(t["email"], _e(ctx.get("client_email")))
        rows += _row(t["country"], _e(ctx.get("country")))
    return rows


def render_client(ctx: dict) -> tuple[str, str]:
    t = _T[ctx["lang"]]
    subject = t["client_subject"].format(ref=ctx["ref"])
    steps = "".join(f'<li style="margin:0 0 6px">{escape(t[k])}</li>' for k in ("next1", "next2", "next3"))
    extra = (
        f'<div style="padding:4px 2px"><p style="margin:0 0 8px;font-size:15px;font-weight:700;color:{INK}">{escape(t["next"])}</p>'
        f'<ul style="margin:0;padding-left:20px;font-size:14px;line-height:1.6;color:#3d4842">{steps}</ul></div>'
    )
    html = _layout(
        title=t["client_title"], preheader=t["client_pre"], hello=t["client_hello"].format(name=ctx["client_name"].split(" ")[0] if ctx["client_name"] else ""),
        intro=t["client_intro"].format(vendor=ctx["vendor_name"]), rows=_details_rows(t, ctx, admin=False), price_html=_price_block(t, ctx["price"]), extra_html=extra,
        cta_label=t["cta_client"], cta_url=f'{settings.public_site_url.rstrip("/")}/client/reservations', foot=t["foot"], foot2=t["foot2"], ref=ctx["ref"],
    )
    return subject, html


def render_admin(ctx: dict) -> tuple[str, str]:
    t = _T["fr"]  # l'equipe travaille en francais
    subject = t["admin_subject"].format(ref=ctx["ref"], service=ctx["service"])
    base = settings.admin_panel_url.replace("/admin/login", "").rstrip("/")
    html = _layout(
        title=t["admin_title"], preheader=t["admin_pre"], hello=None, intro=t["admin_intro"], rows=_details_rows(t, {**ctx, "lang": "fr"}, admin=True), price_html=_price_block(t, ctx["price"]),
        extra_html="", cta_label=t["cta_admin"], cta_url=f"{base}/admin/reservations", foot=t["foot"], foot2="Alerte interne : nouvelle réservation.", ref=ctx["ref"],
    )
    return subject, html


def _deliver(to: str, subject: str, html: str, purpose: str, lang: str) -> None:
    if settings.otp_delivery_mode != "live":
        _log.warning("[BOOKING_MAIL:%s] -> %s (mode log, aucun envoi)", purpose, delivery.mask_destination("email", to))
        delivery.OUTBOX.append({"channel": "email", "destination": to, "code": None, "purpose": purpose, "lang": lang, "subject": subject, "html": html})
        return
    try:
        send_email(to, subject, html)
    except MailError as e:
        _log.error("E-mail de reservation (%s) non envoye : %s", purpose, e)


def notify_new_booking(ctx: dict) -> None:
    """A appeler en arriere-plan apres l'enregistrement : e-mail au client + alerte aux administrateurs.
    Ne leve jamais d'exception (la reservation est deja enregistree)."""
    if settings.node_api_url:
        return  # le backend Trankyl envoie deja ses propres e-mails
    try:
        if ctx.get("client_email"):
            subject, html = render_client(ctx)
            _deliver(ctx["client_email"], subject, html, "booking_client", ctx["lang"])
        admins = settings.admin_email_list
        if not admins:
            _log.warning("ADMIN_EMAIL non configure : alerte de reservation %s non envoyee a l'administration.", ctx["ref"])
        subject, html = render_admin(ctx)
        for to in admins:
            _deliver(to, subject, html, "booking_admin", "fr")
    except Exception:  # noqa: BLE001
        _log.exception("Notification de reservation %s en echec", ctx.get("ref"))
