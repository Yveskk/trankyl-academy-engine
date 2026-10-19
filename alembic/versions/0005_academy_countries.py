"""Pays geres depuis l'admin (menu Configuration) : ils alimentent la bande
verte du site (selecteur de pays, moyens de paiement, lien d'aide) et le
filtrage des prestataires par pays.

Additif uniquement : nouvelle table `academy_countries`, VIDE a la creation.
Tant qu'aucun pays n'y est enregistre, le site garde son comportement actuel
(liste de la section `topbar`, identifiants de pays du code).

`marketplace_country_id` relie (sans cle etrangere, pour ne pas coupler les
bases) un pays Academy a la table `countries` du marketplace Trankyl.

Revision ID: 0005_academy_countries
Revises: 0004_provider_profile_details
"""
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.db.migration_utils import create_index_if_missing, create_table_if_missing

revision = "0005_academy_countries"
down_revision = "0004_provider_profile_details"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    create_table_if_missing(
        "academy_countries",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(2), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=True),
        sa.Column("marketplace_country_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("calling_code", sa.String(8), nullable=True),
        sa.Column("currency_code", sa.String(8), nullable=True),
        sa.Column("payment_text", sa.String(255), nullable=True),
        sa.Column("payment_text_en", sa.String(255), nullable=True),
        sa.Column("help_url", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("uq_academy_countries_code", "academy_countries", ["code"], unique=True)
    create_index_if_missing("ix_academy_countries_active", "academy_countries", ["is_active", "sort_order"])


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de donnees de production.
    pass
