"""Mots-cles francais associes a chaque metier reel du catalogue Academy
(memes codes que `academy_metiers.code`), utilises par les reponses de
repli (sans cle API Gemini) de SITA, aussi bien pour le matching client
que pour l'orientation formation."""

METIER_KEYWORDS: dict[str, list[str]] = {
    "babysitting": ["enfant", "bebe", "bébé", "nounou", "garde", "babysitting", "petit"],
    "cuisine": ["cuisine", "repas", "cuisinier", "cuisiniere", "cuisinière", "chef", "plat", "cuisiner"],
    "courses-shopping": ["course", "courses", "shopping", "achat", "marche", "marché"],
    "aide-travaux-domestiques": ["bricolage", "travaux", "reparation", "réparation", "domestique", "montage"],
    "nettoyage-maison": ["menage", "ménage", "nettoyage maison", "maison propre", "femme de menage"],
    "nettoyage-bureau": ["bureau", "nettoyage bureau", "entreprise nettoyage"],
    "nettoyage-vehicules": ["voiture", "vehicule", "véhicule", "lavage auto", "lavage voiture"],
    "nettoyage-piscine": ["piscine"],
    "nettoyage-meubles": ["meuble", "canape", "canapé", "tapis", "fauteuil"],
    "nettoyage-jardin": ["jardin", "jardinage", "pelouse", "exterieur", "extérieur"],
}


def detect_metier_code(message: str) -> str | None:
    msg_lower = message.lower()
    for code, keywords in METIER_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            return code
    return None
