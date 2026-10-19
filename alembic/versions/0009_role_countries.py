"""Pays dans lesquels un role est proposable (table `academy_role_countries`).

Additif : nouvelle table uniquement. Un role sans ligne est proposable dans tous les pays
(comportement historique) ; avec des lignes, uniquement dans ces pays.

Revision ID: 0009_role_countries
Revises: 0008_country_scope
"""
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.db.migration_utils import create_index_if_missing, create_table_if_missing

revision = "0009_role_countries"
down_revision = "0008_country_scope"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)


def upgrade() -> None:
    create_table_if_missing(
        "academy_role_countries",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("role_id", BIGINT_U, nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    create_index_if_missing("ux_academy_role_countries", "academy_role_countries", ["role_id", "country_code"], unique=True)


def downgrade() -> None:
    pass
