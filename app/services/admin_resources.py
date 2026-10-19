"""Ressources d'administration reprises de l'ancien panneau Angular (coupons, clients, villes, quartiers, categories, unites,
codes de parrainage, demandes de reservation, demandes de suppression, notifications).

Chaque ressource est DECLAREE ici (table, champs, filtres, actions) ; un seul routeur generique (`endpoints/admin_resources.py`)
et une seule page generique cote site les servent. Les tables sont celles de la base partagee avec le backend Trankyl : on lit
les colonnes reellement presentes (la base de developpement peut avoir du retard sur la production) et on n'ecrit que celles-ci."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.ids import generate_unique_id
from app.core.security import hash_password


class ResourceError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Field:
    name: str
    label: str
    kind: str = "text"  # text | textarea | number | select | switch | image | password | email | tel
    required: bool = False
    options: list[tuple[str, str]] | None = None
    lookup: str | None = None  # cle d'une autre ressource dont on propose les lignes
    default: Any = None
    help: str | None = None
    readonly: bool = False
    in_form: bool = True
    in_list: bool = True
    list_kind: str | None = None  # text | badge | bool | date | money | image | code
    on: Any = 1
    off: Any = 0
    max: int | None = None
    create_only: bool = False
    upper: bool = False
    unique: bool = False
    width: str | None = None


@dataclass
class Action:
    key: str
    label: str
    handler: Callable[[Session, dict, Any], str]  # (db, ligne, admin) -> message
    tone: str = "default"  # default | danger
    confirm: str | None = None
    when: Callable[[dict], bool] | None = None


@dataclass
class Resource:
    key: str
    title: str
    singular: str
    perm: str  # menu de permission : academy.<perm>.view / .manage
    table: str
    pk: str
    fields: list[Field]
    label_col: str | None = None
    label_sql: str | None = None  # expression SQL (alias t) pour un libelle compose, a defaut `label_col`
    search: list[str] = field(default_factory=list)
    order: str = ""
    created_col: str | None = None
    description: str = ""
    scope: Callable[[Session, str], tuple[str, dict]] | None = None  # (db, code pays) -> (clause SQL sur t, parametres)
    filters: list[dict] = field(default_factory=list)  # {key, label, options | lookup, sql: {valeur: clause}}
    allow_create: bool = True
    allow_update: bool = True
    allow_delete: bool = True
    hidden: bool = False  # ressource de reference seulement (listes deroulantes)
    actions: list[Action] = field(default_factory=list)
    hide_cols: set[str] = field(default_factory=lambda: {"client_password", "client_token"})
    base_where: str = ""
    before_save: Callable[[Session, dict, bool], dict] | None = None  # (db, donnees, creation) -> donnees
    create_handler: Callable[[Session, dict, Any], dict] | None = None
    delete_handler: Callable[[Session, dict, Any], None] | None = None
    can_delete: Callable[[dict], bool] | None = None
    list_extra: list[str] = field(default_factory=list)  # expressions SQL supplementaires : "(...) AS alias"
    list_columns: list[dict] = field(default_factory=list)  # colonnes de tableau hors champs (ex. calculees)
    dependents: list[tuple[str, str, str]] = field(default_factory=list)  # (table, colonne, libelle) : empechent la suppression si utilises


# --------------------------------------------------------------------------- outils
_cols_cache: dict[str, set[str]] = {}


def columns_of(db: Session, table: str) -> set[str]:
    if table not in _cols_cache:
        insp = inspect(db.get_bind())
        if not insp.has_table(table):
            raise ResourceError(f"La table « {table} » n'existe pas dans cette base : ce menu n'est pas disponible ici.", 503)
        _cols_cache[table] = {c["name"] for c in insp.get_columns(table)}
    return _cols_cache[table]


def country_id(db: Session, code: str) -> int | None:
    return db.execute(text("SELECT country_id FROM countries WHERE country_code=:c"), {"c": code}).scalar()


def jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


# --------------------------------------------------------------------------- portees par pays
def _scope_cities(db, code):
    cid = country_id(db, code)
    return ("t.city_country_id = :cid", {"cid": cid}) if cid else ("1=0", {})


def _scope_districts(db, code):
    cid = country_id(db, code)
    return ("t.district_city_id IN (SELECT city_id FROM cities WHERE city_country_id = :cid)", {"cid": cid}) if cid else ("1=0", {})


def _scope_clients(db, code):
    cid = country_id(db, code)
    return ("(t.client_country_id = :cid OR t.client_country_id IS NULL)", {"cid": cid}) if cid else ("1=1", {})


# --------------------------------------------------------------------------- actions
def _treat_request(db, row, admin):
    db.execute(text("UPDATE booking_requests SET bkr_treated_at=:n, bkr_updated_at=:n WHERE bkr_id=:i"), {"n": datetime.utcnow(), "i": row["bkr_id"]})
    return "Demande marquée comme traitée."


def _treat_deletion(db, row, admin):
    db.execute(text("UPDATE account_deletion_requests SET acc_del_state=1 WHERE acc_del_id=:i"), {"i": row["acc_del_id"]})
    return "Demande marquée comme traitée."


def _delete_account(db, row, admin):
    """Suppression du compte demandee : le compte est desactive et marque supprime (aucune donnee n'est detruite)."""
    owner, kind = row["acc_del_owner_id"], (row["acc_del_type"] or "").lower()
    if kind.startswith("client"):
        db.execute(text("UPDATE clients SET client_is_deleted='1', client_is_active=0 WHERE client_id=:i"), {"i": owner})
    elif kind.startswith("vendor") or kind.startswith("prest"):
        db.execute(text("UPDATE vendors SET vendor_account_deleted=1, vendor_is_active='0' WHERE vendor_id=:i"), {"i": owner})
    else:
        raise ResourceError("Type de compte inconnu : suppression impossible.", 409)
    db.execute(text("UPDATE account_deletion_requests SET acc_del_state=1 WHERE acc_del_id=:i"), {"i": row["acc_del_id"]})
    return "Compte désactivé et marqué comme supprimé."


def _restore_client(db, row, admin):
    db.execute(text("UPDATE clients SET client_is_deleted='0', client_is_active=1 WHERE client_id=:i"), {"i": row["client_id"]})
    return "Compte restauré."


def _toggle_client(db, row, admin):
    new = 0 if str(row["client_is_active"]) == "1" else 1
    db.execute(text("UPDATE clients SET client_is_active=:v WHERE client_id=:i"), {"v": new, "i": row["client_id"]})
    return "Compte activé." if new else "Compte désactivé."


# --------------------------------------------------------------------------- hooks d'ecriture
def _before_client(db, data, creating):
    if creating:
        if not data.get("client_password"):
            raise ResourceError("Le mot de passe est obligatoire.")
        if len(data["client_password"]) < 8:
            raise ResourceError("Le mot de passe doit contenir au moins 8 caractères.")
        if db.execute(text("SELECT 1 FROM clients WHERE client_email=:e"), {"e": data["client_email"]}).first():
            raise ResourceError("Un client utilise déjà cette adresse e-mail.", 409)
        data["client_password"] = hash_password(data["client_password"])
        data["client_unique_id"] = generate_unique_id("CLI")
        data["client_is_deleted"] = "0"
        data.setdefault("client_if_prof_comp", "0")
    return data


def _before_code(db, data, creating):
    return data


def _delete_client(db, row, admin):
    db.execute(text("UPDATE clients SET client_is_deleted='1', client_is_active=0 WHERE client_id=:i"), {"i": row["client_id"]})


def _create_notification(db, data, admin):
    """Meme enregistrement que le backend Trankyl (ligne lisible dans l'application ciblee). L'envoi PUSH (Firebase) reste
    assure par le backend Trankyl : Academy n'a pas les identifiants FCM."""
    now = datetime.utcnow()
    cols = columns_of(db, "notifications")
    target = data["noti_to"]
    user_id = (data.get("user_id") or "").strip()
    user_type = data.get("user_type") or ("client" if target == "client" else "vendor")
    row = {"noti_title": data["noti_title"], "noti_desp": data["noti_desp"], "noti_date": now.isoformat(), "noti_created_at": now, "noti_to": target}
    if user_id:
        if not user_id.isdigit():
            raise ResourceError("Identifiant utilisateur invalide.")
        table, pk = ("vendors", "vendor_id") if user_type == "vendor" else ("clients", "client_id")
        if not db.execute(text(f"SELECT 1 FROM {table} WHERE {pk}=:i"), {"i": int(user_id)}).first():
            raise ResourceError(f"{'Prestataire' if user_type == 'vendor' else 'Client'} #{user_id} introuvable.", 404)
        row["noti_to"] = user_type
        if user_type == "vendor" and "noti_vendor_id" in cols:
            row["noti_vendor_id"] = int(user_id)
        elif "noti_data" in cols:
            row["noti_data"] = json.dumps({"noti_client_id": user_id})
    row = {k: v for k, v in row.items() if k in cols}
    keys = ", ".join(row)
    db.execute(text(f"INSERT INTO notifications ({keys}) VALUES ({', '.join(':' + k for k in row)})"), row)
    return row


# --------------------------------------------------------------------------- definitions
YESNO = [("1", "Actif"), ("0", "Inactif")]

RESOURCES: dict[str, Resource] = {}


def _add(r: Resource) -> None:
    RESOURCES[r.key] = r


_add(Resource(
    key="countries", title="Pays", singular="pays", perm="geo", table="countries", pk="country_id", label_col="country_name", hidden=True,
    fields=[Field("country_name", "Pays")], allow_create=False, allow_update=False, allow_delete=False, order="t.country_name",
))

_add(Resource(
    key="pays", title="Pays", singular="pays", perm="geo", table="countries", pk="country_id", label_col="country_name", search=["country_name", "country_code"], order="t.country_name",
    description="Pays du marketplace Trankyl : un pays « avec service » peut accueillir des prestataires et des réservations. Les villes et quartiers s'y rattachent.",
    fields=[
        Field("country_name", "Pays", required=True, max=255),
        Field("country_code", "Code ISO", required=True, max=10, upper=True, unique=True, help="Ex. TG, CI, BJ."),
        Field("country_calling_codes", "Indicatif", required=True, max=10, help="Ex. +228."),
        Field("country_has_service", "Services disponibles", "switch", default="1", on="1", off="0", list_kind="bool"),
        Field("country_is_active", "Actif", "switch", default=1, list_kind="bool"),
    ],
    filters=[{"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.country_is_active = 1", "0": "t.country_is_active = 0"}}],
    dependents=[("cities", "city_country_id", "ville(s)")], allow_delete=False,
))

_add(Resource(
    key="coupons", title="Coupons", singular="coupon", perm="coupons", table="coupons", pk="cp_id", label_col="c_code", search=["c_code"], order="t.cp_id DESC", created_col="cp_created_at",
    description="Codes promo applicables à la réservation. Un coupon n'est utilisable qu'une fois : il est marqué « utilisé » dès qu'un client s'en sert.",
    fields=[
        Field("c_code", "Code", required=True, max=25, upper=True, unique=True, list_kind="code", help="Lettres et chiffres, 25 caractères maximum."),
        Field("c_type", "Type de remise", "select", required=True, options=[("percentage", "Pourcentage (%)"), ("flat", "Montant fixe (FCFA)")], list_kind="badge", default="percentage"),
        Field("c_value", "Valeur", "number", required=True, help="Un pourcentage (ex. 10) ou un montant en FCFA selon le type."),
        Field("c_maxuse", "Utilisations max.", "number", default=1, in_list=False),
        Field("c_isactive", "Actif", "switch", on="1", off="0", default="1", list_kind="bool"),
        Field("c_usedby", "Utilisé par", readonly=True, in_form=False, list_kind="text"),
    ],
    filters=[{"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.c_isactive = '1'", "0": "(t.c_isactive <> '1' OR t.c_isactive IS NULL)"}}],
    list_columns=[],
))

_add(Resource(
    key="cities", title="Villes", singular="ville", perm="geo", table="cities", pk="city_id", label_col="city_name", search=["city_name"], order="t.city_name", created_col="city_created_at",
    description="Villes où les services sont proposés, pour le pays sélectionné.", scope=_scope_cities,
    fields=[
        Field("city_name", "Ville", required=True, max=255),
        Field("city_country_id", "Pays", "select", required=True, lookup="countries"),
        Field("city_is_active", "Active", "switch", default=1, list_kind="bool"),
    ],
    filters=[{"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.city_is_active = 1", "0": "t.city_is_active = 0"}}],
    dependents=[("district", "district_city_id", "quartier(s)")],
))

_add(Resource(
    key="districts", title="Quartiers", singular="quartier", perm="geo", table="district", pk="district_id", label_col="district_name", search=["district_name"], order="t.district_name", created_col="district_created_at",
    description="Quartiers de chaque ville : le client en choisit un à la réservation.", scope=_scope_districts,
    fields=[
        Field("district_name", "Quartier", required=True, max=255),
        Field("district_city_id", "Ville", "select", required=True, lookup="cities"),
        Field("district_is_active", "Actif", "switch", default=1, list_kind="bool"),
    ],
    filters=[{"key": "district_city_id", "label": "Ville", "lookup": "cities", "column": "t.district_city_id"}, {"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.district_is_active = 1", "0": "t.district_is_active = 0"}}],
))

_add(Resource(
    key="categories", title="Catégories", singular="catégorie", perm="catalog", table="categories", pk="cat_id", label_col="cat_name_fr", search=["cat_name_fr", "cat_name_en"], order="t.cat_order, t.cat_id", created_col="cat_created_at",
    description="Grandes familles de services (Nettoyage, Réparation…).",
    fields=[
        Field("cat_image", "Image", "image", default="", list_kind="image"),
        Field("cat_name_fr", "Nom (FR)", required=True, max=255),
        Field("cat_name_en", "Nom (EN)", required=True, max=255),
        Field("cat_desp_fr", "Description (FR)", "textarea", default="", in_list=False),
        Field("cat_desp_en", "Description (EN)", "textarea", default="", in_list=False),
        Field("cat_order", "Ordre d'affichage", "number", default=0),
        Field("cat_is_active", "Active", "switch", default=1, list_kind="bool"),
    ],
    filters=[{"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.cat_is_active = 1", "0": "t.cat_is_active = 0"}}],
    dependents=[("sub_categories", "subcat_cat_id", "sous-catégorie(s)")],
))

_add(Resource(
    key="subcategories", title="Sous-catégories", singular="sous-catégorie", perm="catalog", table="sub_categories", pk="subcat_id", label_col="subcat_name_fr", search=["subcat_name_fr", "subcat_name_en"], order="t.subcat_name_fr", created_col="subcat_created_at",
    description="Métiers proposés dans chaque catégorie (Plomberie, Électricité…) : ce sont eux que les prestataires choisissent pour leurs services.",
    fields=[
        Field("subcat_image", "Image", "image", default="", list_kind="image"),
        Field("subcat_name_fr", "Nom (FR)", required=True, max=255),
        Field("subcat_name_en", "Nom (EN)", required=True, max=255),
        Field("subcat_cat_id", "Catégorie", "select", required=True, lookup="categories"),
        Field("subcat_desp_fr", "Description (FR)", "textarea", default="", in_list=False),
        Field("subcat_desp_en", "Description (EN)", "textarea", default="", in_list=False),
        Field("subcat_is_active", "Active", "switch", default=1, list_kind="bool"),
    ],
    filters=[{"key": "subcat_cat_id", "label": "Catégorie", "lookup": "categories", "column": "t.subcat_cat_id"}, {"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.subcat_is_active = 1", "0": "t.subcat_is_active = 0"}}],
    dependents=[("services", "s_subcat_id", "service(s) de prestataires")],
))

_add(Resource(
    key="unities", title="Unités", singular="unité", perm="catalog", table="service_unities", pk="sv_unit_id", label_col="sv_unit_wording_fr", search=["sv_unit_code", "sv_unit_wording_fr", "sv_unit_wording_en"], order="t.sv_unit_id",
    description="Unités de tarification d'un service (par heure, par vitre, forfait…).",
    fields=[
        Field("sv_unit_code", "Code", required=True, max=50, unique=True, list_kind="code", help="Identifiant technique court (ex. hour, piece)."),
        Field("sv_unit_wording_fr", "Libellé (FR)", required=True, max=100),
        Field("sv_unit_wording_en", "Libellé (EN)", required=True, max=100),
    ],
))

_add(Resource(
    key="referrals", title="Codes de parrainage", singular="code de parrainage", perm="referrals", table="referral_codes", pk="rc_id", label_col="rc_code", search=["rc_code", "rc_name"], order="t.rc_id DESC", created_col="rc_created_at",
    description="Codes que les nouveaux clients saisissent à l'inscription. Le compteur indique combien de comptes les ont utilisés.",
    fields=[
        Field("rc_code", "Code", required=True, max=50, upper=True, unique=True, list_kind="code"),
        Field("rc_name", "Nom / partenaire", required=True, max=255),
        Field("rc_is_active", "Actif", "switch", default=1, list_kind="bool"),
        Field("rc_used_count", "Utilisations", "number", readonly=True, in_form=False),
    ],
    filters=[{"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.rc_is_active = 1", "0": "t.rc_is_active = 0"}}],
))

_add(Resource(
    key="clients", title="Clients", singular="client", perm="clients", table="clients", pk="client_id", label_col="client_name", label_sql="CONCAT_WS(' ', t.client_name, t.client_family_name, '·', t.client_phone)", scope=_scope_clients,
    search=["client_name", "client_family_name", "client_email", "client_phone", "client_unique_id"], order="t.client_id DESC", base_where="t.client_is_deleted = '0'",
    description="Comptes clients du pays sélectionné. La suppression désactive le compte (aucune donnée n'est détruite) : il reste récupérable dans « Supprimés ».",
    fields=[
        Field("client_unique_id", "Identifiant", readonly=True, in_form=False, list_kind="code"),
        Field("client_name", "Prénom(s)", required=True, max=255),
        Field("client_family_name", "Nom", max=255),
        Field("client_email", "E-mail", "email", required=True, max=255, unique=True),
        Field("client_country_code", "Indicatif", "text", max=10, default="228", help="Ex. 228 pour le Togo."),
        Field("client_phone", "Téléphone", "tel", required=True, max=50),
        Field("client_address", "Adresse", "textarea", in_list=False),
        Field("client_password", "Mot de passe", "password", create_only=True, in_list=False, help="8 caractères minimum. Non modifiable ici après création."),
        Field("client_is_active", "Actif", "switch", default=1, list_kind="bool"),
    ],
    filters=[
        {"key": "active", "label": "Statut", "options": YESNO, "sql": {"1": "t.client_is_active = 1", "0": "t.client_is_active = 0"}},
        {"key": "deleted", "label": "Corbeille", "options": [("0", "Comptes actifs"), ("1", "Supprimés")], "sql": {"0": "t.client_is_deleted = '0'", "1": "t.client_is_deleted = '1'"}, "replaces_base": True},
    ],
    before_save=_before_client, delete_handler=_delete_client,
    actions=[
        Action("toggle", "Activer / désactiver", _toggle_client, when=lambda r: str(r.get("client_is_deleted")) != "1"),
        Action("restore", "Restaurer", _restore_client, when=lambda r: str(r.get("client_is_deleted")) == "1"),
    ],
    can_delete=lambda r: str(r.get("client_is_deleted")) != "1",
))

_add(Resource(
    key="service_ref", title="Services", singular="service", perm="requests", table="services", pk="s_id", label_col="s_title", hidden=True, fields=[Field("s_title", "Service")],
    allow_create=False, allow_update=False, allow_delete=False, order="t.s_title",
))

_add(Resource(
    key="booking_requests", title="Demandes de réservation", singular="demande", perm="requests", table="booking_requests", pk="bkr_id", label_col="bkr_client_name", created_col="bkr_created_at",
    search=["bkr_client_name", "bkr_client_phone_number", "bkr_service_place"], order="t.bkr_id DESC",
    description="Demandes de réservation saisies pour un client (par téléphone, WhatsApp…) et à traiter par l'équipe.",
    fields=[
        Field("bkr_client_name", "Nom du client", required=True, max=150),
        Field("bkr_client_phone_number", "Téléphone", "tel", required=True, max=150),
        Field("bkr_service_id", "Service demandé", "select", lookup="service_ref"),
        Field("bkr_city_id", "Ville", "select", lookup="cities"),
        Field("bkr_service_place", "Lieu de la prestation", max=150),
        Field("bkr_additionnal_infos", "Informations complémentaires", "textarea", max=255, in_list=False),
        Field("bkr_treated_at", "Traitée le", "text", readonly=True, in_form=False, list_kind="date"),
    ],
    filters=[{"key": "treated", "label": "État", "options": [("0", "À traiter"), ("1", "Traitées")], "sql": {"0": "t.bkr_treated_at IS NULL", "1": "t.bkr_treated_at IS NOT NULL"}}],
    actions=[Action("treat", "Marquer traitée", _treat_request, when=lambda r: not r.get("bkr_treated_at"))],
))

_add(Resource(
    key="account_deletions", title="Suppressions de compte", singular="demande", perm="deletions", table="account_deletion_requests", pk="acc_del_id", created_col="acc_del_created_at",
    search=["acc_del_name", "acc_del_email", "acc_del_phone_number"], order="t.acc_del_id DESC", allow_create=False, allow_update=False,
    description="Demandes de suppression de compte reçues depuis les applications. « Désactiver le compte » désactive le compte concerné et clôt la demande.",
    fields=[
        Field("acc_del_type", "Type de compte", readonly=True, in_form=False, list_kind="badge"),
        Field("acc_del_name", "Nom", readonly=True, in_form=False),
        Field("acc_del_phone_number", "Téléphone", readonly=True, in_form=False),
        Field("acc_del_email", "E-mail", readonly=True, in_form=False),
        Field("acc_del_pattern", "Motif", readonly=True, in_form=False),
        Field("acc_del_state", "État", readonly=True, in_form=False, list_kind="badge", options=[("0", "À traiter"), ("1", "Traitée")]),
    ],
    filters=[{"key": "state", "label": "État", "options": [("0", "À traiter"), ("1", "Traitées")], "sql": {"0": "(t.acc_del_state IS NULL OR t.acc_del_state = 0)", "1": "t.acc_del_state = 1"}}],
    actions=[
        Action("delete_account", "Désactiver le compte", _delete_account, tone="danger", confirm="Le compte concerné sera désactivé et marqué comme supprimé. Continuer ?", when=lambda r: str(r.get("acc_del_state") or 0) != "1"),
        Action("treat", "Marquer traitée", _treat_deletion, when=lambda r: str(r.get("acc_del_state") or 0) != "1"),
    ],
))

_add(Resource(
    key="notifications", title="Notifications", singular="notification", perm="notifications", table="notifications", pk="noti_id", created_col="noti_created_at",
    search=["noti_title", "noti_desp"], order="t.noti_id DESC", allow_update=False,
    description="Notifications visibles dans les applications Client et Prestataire. L'envoi du « push » sur les téléphones est assuré par le backend Trankyl.",
    fields=[
        Field("noti_title", "Titre", required=True, max=255),
        Field("noti_desp", "Message", "textarea", required=True),
        Field("noti_to", "Destinataires", "select", required=True, options=[("all", "Tout le monde"), ("client", "Clients"), ("vendor", "Prestataires")], list_kind="badge", default="all"),
        Field("user_type", "Utilisateur précis : type", "select", options=[("", "—"), ("client", "Client"), ("vendor", "Prestataire")], in_list=False, create_only=True, help="Optionnel : pour écrire à une seule personne."),
        Field("user_id", "Utilisateur précis : identifiant", "text", in_list=False, create_only=True, max=20, help="L'identifiant numérique du client ou du prestataire."),
    ],
    create_handler=_create_notification,
))


def get(key: str) -> Resource:
    r = RESOURCES.get(key)
    if r is None:
        raise ResourceError("Ressource inconnue.", 404)
    return r
