"""Pays de l'Academy (table `academy_countries`) : lecture pour le site public
et resolution code -> identifiant du pays marketplace.

Tant que la table est vide, le comportement historique est conserve (liste de
la section `topbar`, identifiants du code) : ajouter cette table ne change rien
tant que l'admin n'y a pas enregistre de pays."""
import threading
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

# Identifiants historiques du marketplace (table `countries`), utilises tant
# qu'aucun pays Academy n'est configure.
LEGACY_MARKETPLACE_IDS = {"TG": 217, "BJ": 23, "CI": 52, "ML": 131, "CM": 36}

_cache: tuple[float, list[dict]] | None = None
_lock = threading.Lock()
_TTL = 30


def invalidate_countries_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def active_countries(db: Session) -> list[dict]:
    """Pays actifs, ordonnes (cache memoire 30 s, vide a chaque ecriture admin)."""
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache and _cache[0] > now:
            return _cache[1]
    rows = db.execute(
        text(
            "SELECT code, name, name_en, marketplace_country_id, calling_code, currency_code, payment_text, payment_text_en, help_url, is_default "
            "FROM academy_countries WHERE is_active=1 ORDER BY sort_order, name"
        )
    ).fetchall()
    data = [
        {
            "code": r[0], "name": r[1], "name_en": r[2], "marketplace_country_id": r[3], "calling_code": r[4], "currency_code": r[5],
            "payment_text": r[6], "payment_text_en": r[7], "help_url": r[8], "is_default": bool(r[9]),
        }
        for r in rows
    ]
    with _lock:
        _cache = (now + _TTL, data)
    return data


def marketplace_country_id(db: Session, code: str) -> int | None:
    """Identifiant du pays dans le marketplace pour filtrer les prestataires.
    None = pas de filtre par pays."""
    code = (code or "").upper()
    countries = active_countries(db)
    if countries:
        for c in countries:
            if c["code"] == code:
                return c["marketplace_country_id"]
        return None
    return LEGACY_MARKETPLACE_IDS.get(code)


def reference_country(db: Session) -> str:
    """Pays par defaut / de reference : celui des donnees historiques (prestataires sans pays, contenu existant)."""
    rows = active_countries(db)
    for c in rows:
        if c["is_default"]:
            return c["code"]
    if rows:
        return rows[0]["code"]
    return "TG"


def vendor_country_clause(db: Session, code: str, alias: str = "v") -> tuple[str, dict]:
    """Condition SQL "ce prestataire/client est dans ce pays", pour les ecrans admin :
      - pays lie a un pays du marketplace : on compare `vendor_country_id` ;
      - les prestataires SANS pays (donnees historiques) appartiennent au pays de reference ;
      - pays sans lien marketplace : aucun prestataire (jamais "tous", pour ne rien melanger).
    Retourne (fragment, parametres)."""
    cid = marketplace_country_id(db, code)
    ref = code == reference_country(db)
    col = f"{alias}.vendor_country_id"
    if cid is not None and ref:
        return f"({col} = :cty_id OR {col} IS NULL)", {"cty_id": cid}
    if cid is not None:
        return f"{col} = :cty_id", {"cty_id": cid}
    if ref:
        return f"{col} IS NULL", {}
    return "1=0", {}


def vendor_in_country(db: Session, vendor_id: int, code: str) -> bool:
    clause, params = vendor_country_clause(db, code, "v")
    return db.execute(text(f"SELECT 1 FROM vendors v WHERE v.vendor_id=:vid AND {clause}"), {"vid": vendor_id, **params}).first() is not None


def vendors_in_country(db: Session, vendor_ids: list[int], code: str) -> set[int]:
    """Parmi ces prestataires, ceux du pays (pour filtrer des listes deja chargees)."""
    from sqlalchemy import bindparam

    ids = sorted({i for i in vendor_ids if i})
    if not ids:
        return set()
    clause, params = vendor_country_clause(db, code, "v")
    q = text(f"SELECT v.vendor_id FROM vendors v WHERE v.vendor_id IN :ids AND {clause}").bindparams(bindparam("ids", expanding=True))
    return {r[0] for r in db.execute(q, {"ids": ids, **params}).fetchall()}


# ---------------------------------------------------------------------------
# Le pays est porte par le SERVICE (colonne `services.s_country_id`, renseignee par le prestataire quand il
# publie un service), pas par le prestataire : un prestataire apparait dans un pays s'il y publie un service.
# ---------------------------------------------------------------------------
def service_country_clause(db: Session, code: str, alias: str = "s") -> tuple[str, dict]:
    """Condition SQL "ce service est publie dans ce pays". Un service sans pays (donnees historiques)
    appartient au pays de reference ; un pays sans lien marketplace n'a aucun service."""
    cid = marketplace_country_id(db, code)
    ref = code == reference_country(db)
    col = f"{alias}.s_country_id"
    blank = f"({col} IS NULL OR {col} = '')"
    if cid is not None and ref:
        return f"({col} = :sc_id OR {blank})", {"sc_id": str(cid)}
    if cid is not None:
        return f"{col} = :sc_id", {"sc_id": str(cid)}
    if ref:
        return blank, {}
    return "1=0", {}


def provider_offer_clause(db: Session, code: str, alias: str = "v") -> tuple[str, dict]:
    """Condition SQL "ce prestataire est visible dans ce pays" :
      - il y publie au moins un service actif ; OU
      - il n'a encore publie AUCUN service actif (profil en attente, nouveau prestataire) : on retombe alors sur le
        pays de son inscription, pour qu'il reste visible de l'equipe qui doit le verifier."""
    s_clause, s_params = service_country_clause(db, code, "sx")
    v_clause, v_params = vendor_country_clause(db, code, alias)
    sql = (
        f"(EXISTS (SELECT 1 FROM services sx WHERE sx.s_vendor_id = {alias}.vendor_id AND sx.s_is_active='1' AND {s_clause}) "
        f"OR (NOT EXISTS (SELECT 1 FROM services sy WHERE sy.s_vendor_id = {alias}.vendor_id AND sy.s_is_active='1') AND {v_clause}))"
    )
    return sql, {**s_params, **v_params}


def public_provider_clause(db: Session, code: str, alias: str = "v") -> tuple[str, dict]:
    """Comme `provider_offer_clause`, pour le site PUBLIC : exclut en plus les comptes supprimes ou desactives
    (sinon un prestataire sans service actif y resterait visible par le repli sur son pays d'inscription)."""
    sql, params = provider_offer_clause(db, code, alias)
    return f"({sql} AND COALESCE({alias}.vendor_account_deleted, '0') NOT IN ('1', 'true') AND COALESCE({alias}.vendor_is_active, '1') NOT IN ('0', 'false', 'no'))", params


def provider_in_country(db: Session, vendor_id: int, code: str) -> bool:
    clause, params = provider_offer_clause(db, code, "v")
    return db.execute(text(f"SELECT 1 FROM vendors v WHERE v.vendor_id=:vid AND {clause}"), {"vid": vendor_id, **params}).first() is not None
