"""Multi-pays : chaque contenu et chaque acces admin est rattache a un pays.

Additif, sans perte de donnees. Tout le contenu existant est rattache au TOGO ('TG') :
  - `academy_content_sections` : + country_code ; la cle primaire (key) devient (key, country_code)
    pour qu'un meme bloc puisse exister dans chaque pays (les lignes existantes passent a 'TG') ;
  - `academy_home_items`, `academy_banners`, `academy_metiers` : + country_code ('TG' par defaut) ;
  - `academy_admin_countries` (nouvelle) : pays accessibles a chaque administrateur ;
  - `academy_admin_profiles.all_countries` : acces a tous les pays ;
  - `academy_entity_countries` (nouvelle) : rattachement a un pays d'objets des tables partagees
    qu'on ne modifie pas (ex. articles du blog = table `events`).

Revision ID: 0008_country_scope
Revises: 0007_admin_access
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from app.db.migration_utils import add_column_if_missing, create_index_if_missing, create_table_if_missing, has_column, has_index, has_table

revision = "0008_country_scope"
down_revision = "0007_admin_access"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)
NOW = sa.text("CURRENT_TIMESTAMP")
DEFAULT_COUNTRY = "TG"


def _country_column() -> sa.Column:
    return sa.Column("country_code", sa.String(2), nullable=False, server_default=DEFAULT_COUNTRY)


def upgrade() -> None:
    bind = op.get_bind()

    # Blocs de contenu : la cle primaire passe de (key) a (key, country_code).
    
    if has_table("academy_content_sections") and not has_column("academy_content_sections", "country_code"):
        bind.execute(sa.text(
            "ALTER TABLE `academy_content_sections` ADD COLUMN `country_code` VARCHAR(2) NOT NULL DEFAULT 'TG', "
            "DROP PRIMARY KEY, ADD PRIMARY KEY (`key`, `country_code`)"
        ))

    for table, index_cols in (
        ("academy_home_items", ["country_code", "section_key", "is_active", "sort_order"]),
        ("academy_banners", ["country_code", "is_active", "ordre"]),
        ("academy_metiers", ["country_code"]),
    ):
        if has_table(table):
            add_column_if_missing(table, _country_column())
            create_index_if_missing(f"ix_{table}_country", table, index_cols)

    if has_table("academy_admin_profiles"):
        add_column_if_missing("academy_admin_profiles", sa.Column("all_countries", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    create_table_if_missing(
        "academy_admin_countries",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("user_id", BIGINT_U, nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("ux_academy_admin_countries", "academy_admin_countries", ["user_id", "country_code"], unique=True)

    create_table_if_missing(
        "academy_entity_countries",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", BIGINT_U, nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("ux_academy_entity_countries", "academy_entity_countries", ["entity_type", "entity_id"], unique=True)
    create_index_if_missing("ix_academy_entity_countries_country", "academy_entity_countries", ["country_code", "entity_type"])


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de colonnes ni de tables dans la base partagee.
    pass
