"""Exemption de 2FA par compte (comptes de test / developpement).

Additif : une colonne sur `academy_admin_profiles`. Le drapeau n'a d'effet que si le serveur
l'autorise (`ALLOW_MFA_EXEMPT=true`, desactive par defaut) : en production il reste inoperant.

Revision ID: 0011_mfa_exempt
Revises: 0010_metier_code_per_country
"""
import sqlalchemy as sa

from app.db.migration_utils import add_column_if_missing, has_table

revision = "0011_mfa_exempt"
down_revision = "0010_metier_code_per_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if has_table("academy_admin_profiles"):
        add_column_if_missing("academy_admin_profiles", sa.Column("mfa_exempt", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    pass
