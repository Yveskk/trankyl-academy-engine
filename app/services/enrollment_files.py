"""Pieces justificatives de l'enrolement : verification du type reel, envoi vers Cloudinary, contrat signe.

- Le type d'un fichier est lu dans son contenu (signature des premiers octets), jamais d'apres le nom ni l'en-tete envoye.
- Memes formats et memes limites que le backend Trankyl : JPG, PNG, WebP, PDF ; 5 Mo par fichier.
- Meme compte Cloudinary (preset non signe) que le reste du projet : tout vit dans le meme cloud."""
from __future__ import annotations

import io
import os
import textwrap
from datetime import date

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MULTI = 3  # diplomes / CV / cartes CEF : 3 fichiers maximum chacun


class FileRejected(Exception):
    pass


def sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    return None


def check(data: bytes, label: str) -> str:
    if not data:
        raise FileRejected(f"{label} : fichier vide.")
    if len(data) > MAX_FILE_BYTES:
        raise FileRejected(f"{label} : fichier trop volumineux (5 Mo maximum).")
    kind = sniff(data)
    if not kind:
        raise FileRejected(f"{label} : format non supporte (JPG, PNG, WebP ou PDF).")
    return kind


def upload_document(data: bytes, label: str = "Fichier") -> str:
    """Verifie puis envoie un document ; retourne son URL https."""
    check(data, label)
    return _send(data, label)


def _send(data: bytes, label: str) -> str:
    cloud, preset = os.environ.get("CLOUDINARY_CLOUD_NAME"), os.environ.get("CLOUDINARY_UPLOAD_PRESET")
    if not cloud or not preset:
        raise FileRejected("Envoi de fichiers non configure (CLOUDINARY_CLOUD_NAME / CLOUDINARY_UPLOAD_PRESET manquants).")
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(cloud_name=cloud)
    try:
        return cloudinary.uploader.unsigned_upload(data, preset, resource_type="auto")["secure_url"]
    except Exception as e:  # noqa: BLE001
        raise FileRejected(f"{label} : echec de l'envoi ({e}).") from e


# --------------------------------------------------------------------------- contrat
CONTRACT_TEXT = """CONTRAT DE PARTENARIAT — TRANKYL

En devenant prestataire partenaire de Trankyl, j'accepte les conditions suivantes :

1. PARTENARIAT — Je suis partenaire indépendant de Trankyl, pas salarié(e).

2. VALEURS — Transparence, confiance, respect des clients et satisfaction.

3. RESPONSABILITÉ — Je suis responsable de mes services et de ceux qui m'accompagnent.

4. DOMMAGES & VOLS — Je dédommage tout dommage ou vol causé, faute de quoi les autorités seront saisies.

5. IMAGE — Je ne porte pas atteinte à l'image de Trankyl.

6. PROFESSIONNALISME — Ponctualité, respect des délais et des clients.

7. SANCTIONS — Insultes ou agressions entraînent pénalités. Sans immatriculation, je ne délègue pas mes missions.

8. FISCALITÉ — Je déclare mes revenus et paie impôts et cotisations.

9. ABONNEMENT — 500 FCFA/mois à compter de la signature.

10. COMMISSION — 10% à 30% sur chaque prestation.

11. PAIEMENTS — Via Trankyl : sous 7 jours. Direct : commission sous 24h.

12. PRÉAVIS — 1 semaine (pénalité 30%, min 20 000 FCFA). Annulation < 24h : 20%, min 1 000 FCFA.

13. RETARD — 10 000 FCFA. Retard paiement : +20%/semaine.

14. GARANTIE — « Satisfait ou remboursé ».

15. SUSPENSION — Compte suspendu en cas de non-respect, 3 annulations ou non-reversement.

16. CONTACT — Je signale tout contact direct d'un client.

17. DONNÉES — Traitées selon la politique de confidentialité.

18. RUPTURE — Informer contact@trankyl.me. Commissions dues restent exigibles.

19. CGU — J'accepte les CGU de Trankyl.

20. ACCEPTATION — J'accepte d'être prestataire partenaire de Trankyl."""


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def signature_png(signature_data_uri: str):
    """Decode la signature (data URI image) ; None si elle n'est pas exploitable."""
    import base64

    from PIL import Image

    if not signature_data_uri or not signature_data_uri.startswith("data:image"):
        return None
    try:
        raw = base64.b64decode(signature_data_uri.split(",", 1)[1], validate=False)
        if len(raw) > 1_500_000 or not sniff(raw):
            return None
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        return img
    except Exception:  # noqa: BLE001
        return None


def contract_image(signature_data_uri: str, signer: str = "") -> bytes:
    """Contrat de partenariat signe, en PNG (meme mise en page que celle du backend Trankyl)."""
    from PIL import Image, ImageDraw

    W, M = 800, 60
    body, small, title, head = _font(14), _font(12), _font(22, True), _font(14, True)
    lines: list[str] = []
    for raw in CONTRACT_TEXT.split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        lines += textwrap.wrap(raw, 88) or [raw]
    line_h, top = 22, 150
    sig_y = top + len(lines) * line_h + 40
    H = sig_y + 190
    img = Image.new("RGB", (W, H), "#f8fafc")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((30, 20, W - 30, H - 20), 16, fill="white", outline="#e2e8f0")
    d.rounded_rectangle((30, 20, W - 30, 100), 16, fill="#03a71a")
    d.rectangle((30, 60, W - 30, 100), fill="#03a71a")
    d.text((W / 2, 52), "CONTRAT DE PARTENARIAT", font=title, fill="white", anchor="ms")
    d.text((W / 2, 82), "TRANKYL — Prestataire Partenaire", font=small, fill="#dff5e3", anchor="ms")
    y = top
    for ln in lines:
        d.text((M, y), ln, font=body, fill="#334155")
        y += line_h
    d.text((M, sig_y), "Signature du prestataire :" + (f"  {signer}" if signer else ""), font=head, fill="#111827")
    d.text((M, sig_y + 22), f"Date : {date.today().strftime('%d/%m/%Y')}", font=small, fill="#6b7280")
    d.rounded_rectangle((M, sig_y + 48, M + 260, sig_y + 138), 8, fill="#f9fafb", outline="#e5e7eb")
    sig = signature_png(signature_data_uri)
    if sig is not None:
        sig.thumbnail((240, 80))
        img.paste(sig, (M + 10, sig_y + 53), sig)
    d.text((W / 2, H - 38), "Contrat généré par Trankyl Academy", font=_font(10), fill="#9ca3af", anchor="ms")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
