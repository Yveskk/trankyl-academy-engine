"""Menus d'administration repris de l'ancien panneau (coupons, parrainage, notifications...).

Additif et idempotent : ces objets existent deja dans la base de production du backend Trankyl ; on ne cree que ce qui manque
(typiquement en developpement) : la table `referral_codes` et les colonnes `noti_vendor_id` / `noti_data` de `notifications`.

Revision ID: 0014_admin_catalog
Revises: 0013_vendor_enrollments
"""
import sqlalchemy as sa

from app.db.migration_utils import add_column_if_missing, create_table_if_missing, has_table

revision = "0014_admin_catalog"
down_revision = "0013_vendor_enrollments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "referral_codes",
        sa.Column("rc_id", sa.BigInteger().with_variant(sa.dialects.mysql.BIGINT(unsigned=True), "mysql"), primary_key=True, autoincrement=True),
        sa.Column("rc_code", sa.String(50), nullable=False, unique=True),
        sa.Column("rc_name", sa.String(255), nullable=False),
        sa.Column("rc_is_active", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("rc_used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rc_created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("rc_updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    if has_table("notifications"):
        add_column_if_missing("notifications", sa.Column("noti_vendor_id", sa.BigInteger().with_variant(sa.dialects.mysql.BIGINT(unsigned=True), "mysql"), nullable=True))
        add_column_if_missing("notifications", sa.Column("noti_data", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
