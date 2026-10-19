"""E-mails du parcours d'enrolement : alerte a l'administration (dossier soumis) et decision au prestataire.

Meme modele HTML et memes regles que les e-mails de reservation (tout est echappe, envoi en arriere-plan, jamais bloquant,
mode `log` en developpement)."""
from __future__ import annotations

import logging
from html import escape

from app.core.config import settings
from app.services.booking_mail import GREEN, INK, MUTED, _deliver, _e, _layout, _row

_log = logging.getLogger("enrollment-mail")

_STUDY = {"aucun": "Aucune scolarité", "primaire": "Primaire", "college": "Collège / BEPC", "lycee": "Lycée / BAC", "bts": "BTS / DUT", "licence": "Licence (Bac+3)", "master": "Master (Bac+5)", "doctorat": "Doctorat", "formation": "Formation professionnelle", "autre": "Autre"}


def _admin_url() -> str:
    base = settings.admin_panel_url.rsplit("/admin", 1)[0]
    return f"{base}/admin/enrolements"


def render_admin(ctx: dict) -> tuple[str, str]:
    """ctx : vendor_name, vendor_phone, vendor_email, resubmitted, study_level, languages, company_name, country, enrollment_id."""
    redo = ctx.get("resubmitted")
    title = "Dossier d'enrôlement mis à jour" if redo else "Nouveau dossier d'enrôlement"
    rows = _row("Prestataire", _e(ctx["vendor_name"]))
    rows += _row("Téléphone", _e(ctx.get("vendor_phone")))
    rows += _row("Email", _e(ctx.get("vendor_email")))
    rows += _row("Pays", _e(ctx.get("country")))
    rows += _row("Niveau d'études", _e(_STUDY.get(ctx.get("study_level") or "", ctx.get("study_level"))))
    rows += _row("Langues", _e(ctx.get("languages")))
    if ctx.get("company_name"):
        rows += _row("Entreprise", _e(ctx["company_name"]))
    html = _layout(
        title=title, preheader=f"{ctx['vendor_name']} a soumis son dossier d'enrôlement.", hello=None,
        intro=f"{ctx['vendor_name']} vient de {'mettre à jour' if redo else 'soumettre'} son formulaire d'enrôlement. Vérifiez les informations et les pièces, puis approuvez ou refusez le dossier.",
        rows=rows, price_html="", extra_html="", cta_label="Examiner le dossier", cta_url=_admin_url(),
        foot="Trankyl Academy — alerte interne.", foot2="Dossier d'enrôlement prestataire.", ref=f"#{ctx.get('enrollment_id', '')}",
    )
    return f"{'Dossier mis à jour' if redo else 'Nouveau dossier d’enrôlement'} — {ctx['vendor_name']}", html


def render_decision(ctx: dict) -> tuple[str, str]:
    """ctx : vendor_name, decision (approved|rejected), note, missing (liste de libelles)."""
    ok = ctx["decision"] == "approved"
    missing = ctx.get("missing") or []
    if ok:
        title, intro = "Dossier approuvé", "Félicitations ! Votre dossier d'enrôlement a été approuvé. Vous pouvez désormais recevoir des missions."
        if missing:
            intro = "Votre dossier d'enrôlement a été approuvé. Il reste cependant des informations à compléter :"
    else:
        title, intro = "Dossier refusé", ctx.get("note") or "Votre dossier d'enrôlement a été refusé."
    extra = ""
    items = missing if ok else (ctx.get("missing") or [])
    if items:
        lis = "".join(f'<li style="margin:2px 0">{escape(str(i))}</li>' for i in items)
        label = "À compléter" if ok else "Éléments à corriger"
        extra = f'<p style="margin:0 0 6px;font-size:14px;font-weight:700;color:{INK}">{label}</p><ul style="margin:0 0 8px;padding-left:20px;font-size:14px;color:{MUTED}">{lis}</ul>'
    if not ok and ctx.get("note") and intro != ctx["note"]:
        extra = f'<p style="margin:0 0 10px;font-size:14px;color:{INK}"><strong>Motif :</strong> {escape(ctx["note"])}</p>' + extra
    html = _layout(
        title=title, preheader=title, hello=f"Bonjour {ctx['vendor_name']},", intro=intro, rows="", price_html="", extra_html=extra,
        cta_label="Ouvrir mon espace", cta_url=ctx.get("space_url") or "https://trankyl.com", foot="Trankyl Academy — des prestataires vérifiés, près de chez vous.",
        foot2="Vous recevez cet e-mail car vous avez soumis un dossier d'enrôlement.", ref="Enrôlement",
    )
    return f"{title} — Trankyl", html


def notify_submission(ctx: dict) -> None:
    """Alerte aux administrateurs. Ne leve jamais d'exception (le dossier est deja enregistre)."""
    try:
        admins = settings.admin_email_list
        if not admins:
            _log.warning("ADMIN_EMAIL non configure : alerte d'enrolement de %s non envoyee.", ctx.get("vendor_name"))
            return
        subject, html = render_admin(ctx)
        for to in admins:
            _deliver(to, subject, html, "enrollment_admin", "fr")
    except Exception:  # noqa: BLE001
        _log.exception("Alerte d'enrolement en echec")


def notify_decision(ctx: dict, to_email: str | None) -> None:
    try:
        if not to_email:
            return
        subject, html = render_decision(ctx)
        _deliver(to_email, subject, html, "enrollment_decision", "fr")
    except Exception:  # noqa: BLE001
        _log.exception("E-mail de decision d'enrolement en echec")
