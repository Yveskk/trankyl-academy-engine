_KNOWN_DIAL_CODES = ("228", "229")  # Togo, Benin — seuls pays ou Trankyl a du service (table `countries`)


def phone_lookup_variants(phone: str) -> list[str]:
    """Genere les formes plausibles d'un numero pour la recherche en base.

    Le marketplace Trankyl (trankyl_backend_nodejs) n'a jamais impose une
    convention unique pour `vendor_phone`/`client_phone` (avec ou sans
    indicatif, avec ou sans "+"), alors qu'Academy construit toujours
    "+228XXXXXXXX" a partir du select pays sur ses propres formulaires. On
    essaie donc les 3 formes plausibles pour retrouver aussi bien un compte
    cree via Academy que via le marketplace."""
    stripped = phone.lstrip("+")
    variants = {phone, stripped}
    for code in _KNOWN_DIAL_CODES:
        if stripped.startswith(code):
            variants.add(stripped[len(code):])
    return list(variants)
