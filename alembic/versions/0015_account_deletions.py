"""Suppression de compte en deux temps : delai de reflexion puis anonymisation.

Additif et idempotent. Une ligne par demande de suppression d'un prestataire : tant que `status` vaut `pending`, le compte est
desactive mais peut etre reactive par une simple reconnexion ; a `scheduled_for`, il est anonymise (statut `done`).

Revision ID: 0015_account_deletions
Revises: 0014_admin_catalog
"""
import sqlalchemy as sa

from app.db.migration_utils import create_index_if_missing, create_table_if_missing

revision = "0015_account_deletions"
down_revision = "0014_admin_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "academy_account_deletions",
        sa.Column("id", sa.BigInteger().with_variant(sa.dialects.mysql.BIGINT(unsigned=True), "mysql"), primary_key=True, autoincrement=True),
        sa.Column("vendor_id", sa.BigInteger().with_variant(sa.dialects.mysql.BIGINT(unsigned=True), "mysql"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),  # pending | cancelled | processing | done
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("anonymized_at", sa.DateTime(), nullable=True),
        sa.Column("restore_services", sa.Text(), nullable=True),  # JSON : services visibles avant la demande, remis en ligne si le prestataire revient
        sa.Column("was_active", sa.String(10), nullable=True),
    )
    create_index_if_missing("ix_academy_account_deletions_vendor", "academy_account_deletions", ["vendor_id", "status"])
    create_index_if_missing("ix_academy_account_deletions_due", "academy_account_deletions", ["status", "scheduled_for"])


def downgrade() -> None:
    pass
