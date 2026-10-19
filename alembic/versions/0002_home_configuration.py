"""Configuration de la page d'accueil pilotee depuis l'admin.

Additif uniquement :
  - academy_content_sections : + section_type, sort_order, payload_json(_en)
  - academy_banners          : + titre, sous-titre, CTA, lien, fenetre de validite
  - academy_home_items (nouvelle) : cartes repetables (services, garanties,
    etapes, puces, partenaires, temoignages, prestataires epingles...)

Les lignes existantes gardent toutes leurs valeurs ; les nouvelles colonnes
sont NULL ou ont une valeur par defaut neutre.

Revision ID: 0002_home_configuration
Revises: 0001_baseline
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from app.db.migration_utils import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "0002_home_configuration"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)


def upgrade() -> None:
    # --- academy_content_sections -----------------------------------------
    add_column_if_missing("academy_content_sections", sa.Column("section_type", sa.String(40), nullable=True))
    add_column_if_missing("academy_content_sections", sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")))
    add_column_if_missing("academy_content_sections", sa.Column("payload_json", mysql.LONGTEXT(), nullable=True))
    add_column_if_missing("academy_content_sections", sa.Column("payload_json_en", mysql.LONGTEXT(), nullable=True))

    # --- academy_banners ---------------------------------------------------
    add_column_if_missing("academy_banners", sa.Column("title", sa.String(255), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("title_en", sa.String(255), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("subtitle", sa.Text(), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("subtitle_en", sa.Text(), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("cta_label", sa.String(100), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("cta_label_en", sa.String(100), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("cta_url", sa.String(500), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("starts_at", sa.DateTime(), nullable=True))
    add_column_if_missing("academy_banners", sa.Column("ends_at", sa.DateTime(), nullable=True))

    # --- academy_home_items ------------------------------------------------
    created = create_table_if_missing(
        "academy_home_items",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(40), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("title_en", sa.String(255), nullable=True),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("subtitle_en", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("body_en", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("tone", sa.String(20), nullable=True),
        sa.Column("link_url", sa.String(500), nullable=True),
        sa.Column("ref_type", sa.String(30), nullable=True),
        sa.Column("ref_id", BIGINT_U, nullable=True),
        sa.Column("data_json", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    create_index_if_missing("ix_academy_home_items_section", "academy_home_items", ["section_key", "is_active", "sort_order"])
    create_index_if_missing("ix_academy_home_items_ref", "academy_home_items", ["ref_type", "ref_id"])


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de donnees de production.
    pass
