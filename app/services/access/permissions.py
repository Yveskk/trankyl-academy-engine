"""Catalogue des permissions du panneau d'administration Academy.

Modele (comme dans les grandes organisations) : un ROLE = un ensemble de
permissions ; un utilisateur porte UN role ; chaque menu a une permission
"voir" et des permissions d'action. Les permissions sont stockees dans
`user_types.ust_roles` (JSON), table partagee avec l'admin Trankyl :
  - les cles Academy sont toutes prefixees `academy.` ;
  - les cles qui ne nous appartiennent pas (admin Trankyl : "dashboard",
    "crm.clients"...) sont conservees telles quelles a chaque modification ;
  - `"ADMIN"` (role historique id 1) = super-administrateur : tout est permis.
"""
from __future__ import annotations

import json

SUPER = "ADMIN"
PREFIX = "academy."

# (cle de menu, libelle du menu, [(action, libelle)])  — l'ordre est celui du menu lateral.
CATALOGUE: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("dashboard", "Tableau de bord", [("view", "Consulter")]),
    ("taxonomy", "Taxonomie", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
    ("curriculum", "Curriculum", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
    ("learners", "Apprenants", [("view", "Consulter"), ("manage", "Vérifier l'identité")]),
    ("enrollments", "Inscriptions", [("view", "Consulter")]),
    ("bookings", "Réservations", [("view", "Consulter"), ("manage", "Marquer terminée / annuler")]),
    ("clients", "Clients", [("view", "Consulter"), ("manage", "Créer / modifier / désactiver")]),
    ("coupons", "Coupons", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
    ("geo", "Villes et quartiers", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
    ("catalog", "Catégories, sous-catégories et unités", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
    ("referrals", "Codes de parrainage", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
    ("subscription", "Tarifs d'abonnement", [("view", "Consulter"), ("manage", "Modifier les tarifs")]),
    ("notifications", "Notifications", [("view", "Consulter"), ("manage", "Envoyer / supprimer")]),
    ("deletions", "Suppressions de compte", [("view", "Consulter"), ("manage", "Traiter les demandes")]),
    ("requests", "Demandes de réservation", [("view", "Consulter"), ("manage", "Créer / traiter")]),
    ("payments", "Paiements", [("view", "Consulter")]),
    ("enrollment_forms", "Formulaires d'enrôlement", [("view", "Consulter"), ("manage", "Approuver / refuser")]),
    ("quotes", "Devis", [("view", "Consulter"), ("manage", "Répondre aux demandes")]),
    ("contacts", "Mises en relation", [("view", "Consulter"), ("manage", "Traiter les demandes")]),
    ("blog", "Blog", [("view", "Consulter"), ("manage", "Rédiger / publier / supprimer")]),
    ("home", "Page d'accueil", [("view", "Consulter"), ("manage", "Modifier les sections et cartes")]),
    ("reviews", "Avis", [("view", "Consulter"), ("moderate", "Modérer / répondre")]),
    ("providers", "Prestataires", [("view", "Consulter"), ("manage", "Modifier profils, mise en avant")]),
    ("posters", "Bannière", [("view", "Consulter"), ("manage", "Publier / modifier / supprimer")]),
    ("content", "Contenu du site", [("view", "Consulter"), ("manage", "Modifier")]),
    ("config", "Configuration", [("view", "Consulter"), ("manage", "Modifier (pays...)")]),
    (
        "users",
        "Utilisateurs",
        [
            ("view", "Consulter"),
            ("create", "Créer"),
            ("edit", "Modifier / changer de rôle"),
            ("suspend", "Suspendre / réactiver"),
            ("reset", "Réinitialiser mot de passe / 2FA"),
        ],
    ),
    ("roles", "Rôles", [("view", "Consulter"), ("manage", "Créer / modifier / supprimer")]),
]

# Permissions qui donnent un controle total sur les acces : a ne confier qu'aux administrateurs.
SENSITIVE = {"academy.users.create", "academy.users.edit", "academy.users.suspend", "academy.users.reset", "academy.roles.manage"}

ALL_KEYS: list[str] = [f"{PREFIX}{menu}.{action}" for menu, _, actions in CATALOGUE for action, _ in actions]
_ALL_SET = set(ALL_KEYS)


def catalogue_payload() -> list[dict]:
    return [
        {
            "menu": menu,
            "label": label,
            "actions": [{"key": f"{PREFIX}{menu}.{a}", "action": a, "label": l, "sensitive": f"{PREFIX}{menu}.{a}" in SENSITIVE} for a, l in actions],
        }
        for menu, label, actions in CATALOGUE
    ]


def parse(raw: str | None) -> list[str]:
    """`ust_roles` -> liste de cles (tolere vide / invalide)."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def academy_part(perms: list[str]) -> list[str]:
    return [p for p in perms if p in _ALL_SET]


def merge_for_save(existing: list[str], academy_keys: list[str]) -> list[str]:
    """Remplace la partie Academy d'un role en gardant tout le reste (cles Trankyl, "ADMIN")."""
    keep = [p for p in existing if p not in _ALL_SET and not p.startswith(PREFIX)]
    new = [k for k in ALL_KEYS if k in set(academy_keys)]  # ordre stable, cles inconnues ecartees
    return keep + new


def with_implied(keys: list[str]) -> list[str]:
    """Une action d'ecriture suppose de pouvoir voir le menu."""
    out = set(keys)
    for k in keys:
        if k.startswith(PREFIX):
            menu, _, action = k[len(PREFIX):].rpartition(".")
            if action != "view" and f"{PREFIX}{menu}.view" in _ALL_SET:
                out.add(f"{PREFIX}{menu}.view")
    return [k for k in ALL_KEYS if k in out]


def effective(perms: list[str]) -> tuple[bool, list[str]]:
    """(super_admin, cles Academy effectives)."""
    if SUPER in perms:
        return True, list(ALL_KEYS)
    return False, academy_part(perms)


def grants_panel_access(perms: list[str]) -> bool:
    is_super, keys = effective(perms)
    return is_super or bool(keys)
