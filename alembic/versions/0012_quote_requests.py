"""Demandes de devis (formulaire « Demander un devis » + menu admin « Devis »).

Additif : cree la table `academy_quote_requests` si elle n'existe pas.

Revision ID: 0012_quote_requests
Revises: 0011_mfa_exempt
"""
import sqlalchemy as sa

from app.db.migration_utils import create_index_if_missing, create_table_if_missing

revision = "0012_quote_requests"
down_revision = "0011_mfa_exempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "academy_quote_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="TG"),
        sa.Column("vendor_id", sa.BigInteger(), nullable=False),
        sa.Column("vendor_name", sa.String(255), nullable=True),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("slot_label", sa.String(80), nullable=True),
        sa.Column("lang", sa.String(2), nullable=False, server_default="fr"),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("reply_subject", sa.String(255), nullable=True),
        sa.Column("reply_message", sa.Text(), nullable=True),
        sa.Column("replied_by", sa.String(255), nullable=True),
        sa.Column("replied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_academy_quote_requests_country_status", "academy_quote_requests", ["country_code", "status", "created_at"])


def downgrade() -> None:
    pass
