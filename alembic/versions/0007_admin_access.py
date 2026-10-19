"""Utilisateurs, roles et double authentification (2FA) du panneau admin.

Additif et idempotent. Ne supprime ni ne reecrit aucune donnee :
  - `users` : ajoute `totp_enabled`, `totp_secret`, `totp_recovery_codes`
    (memes noms que l'admin Trankyl / backend Node, qui peut deja les avoir) ;
  - `user_types.ust_roles` : elargi de VARCHAR(255) a TEXT (un role avec beaucoup de
    permissions depasserait 255 caracteres) — aucune valeur modifiee ;
  - `academy_admin_profiles` (nouvelle) : statut du compte (actif/suspendu), mot de passe
    temporaire a changer, dernier pas TOTP accepte (anti-rejeu), createur.

Revision ID: 0007_admin_access
Revises: 0006_security_verification
"""
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.db.migration_utils import add_column_if_missing, create_index_if_missing, create_table_if_missing, has_column, has_table

revision = "0007_admin_access"
down_revision = "0006_security_verification"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    add_column_if_missing("users", sa.Column("totp_enabled", sa.Boolean(), nullable=True, server_default=sa.text("0")))
    add_column_if_missing("users", sa.Column("totp_secret", sa.String(255), nullable=True))
    add_column_if_missing("users", sa.Column("totp_recovery_codes", sa.Text(), nullable=True))

    if has_table("user_types") and has_column("user_types", "ust_roles"):
        bind = op_bind()
        col = bind.execute(
            sa.text("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='user_types' AND COLUMN_NAME='ust_roles'")
        ).scalar()
        if (col or "").lower() == "varchar":
            bind.execute(sa.text("ALTER TABLE `user_types` MODIFY `ust_roles` TEXT NULL"))

    created = create_table_if_missing(
        "academy_admin_profiles",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("user_id", BIGINT_U, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),  # active | suspended
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("totp_enabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", BIGINT_U, nullable=True),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("ux_academy_admin_profiles_user", "academy_admin_profiles", ["user_id"], unique=True)


def op_bind():
    from alembic import op

    return op.get_bind()


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de colonnes ni de tables dans la base partagee.
    pass
