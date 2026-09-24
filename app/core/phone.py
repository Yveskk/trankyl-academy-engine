_KNOWN_DIAL_CODES = ("228", "229")  # Togo, Benin — seuls pays ou Trankyl a du service (table `countries`)

# Le champ telephone accepte n'importe quel pays (comme le picker complet des
# vraies apps vendor/client), pas seulement Togo/Benin — country_has_service
# ne concerne que le pays ou une prestation est realisee, pas l'origine du
# numero. Mais la CONVENTION DE STOCKAGE reelle differe selon le pays : pour
# Togo/Benin, l'ecrasante majorite des comptes reels stockent le numero
# national seul, sans indicatif ni "+" (ex. "90331380"). Pour les autres
# pays, les comptes reels existants gardent l'indicatif complet avec "+"
# (ex. "+33672824623", "+18094277029", "+243819074132" — verifie en base).


def normalize_phone_for_storage(phone: str) -> str:
    """Reproduit la convention de stockage reelle du marketplace Trankyl
    selon le pays : numero national seul pour Togo/Benin, "+indicatif..."
    tel quel pour les autres pays. A utiliser a l'inscription :
    trankyl_backend_nodejs (l'app vendor/client reelle) fait une recherche
    EXACTE sur vendor_phone/client_phone pour la connexion et le mot de
    passe oublie (pas de tolerance de format comme pour la recherche de
    doublons) — un compte cree par Academy dans un format qui ne correspond
    a aucune de ces deux conventions ne serait donc jamais retrouve par ces
    parcours cote app reelle, meme si le mot de passe est correct."""
    stripped = phone.lstrip("+")
    for code in _KNOWN_DIAL_CODES:
        if stripped.startswith(code):
            return stripped[len(code):]
    return phone if phone.startswith("+") else f"+{stripped}"


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
