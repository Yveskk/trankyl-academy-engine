"""Verification par code et securite des comptes (inscription, connexion,
mot de passe oublie) : WhatsApp / SMS / email.

Additif uniquement : 4 nouvelles tables, aucune modification des tables
partagees (`vendors`, `clients`, `users`). Les comptes existants n'ont pas de
ligne de securite : ils sont verifies progressivement a leur prochaine
connexion, sans etre bloques.

  - academy_verifications     : codes a usage unique (STOCKES HACHES, jamais en clair)
  - academy_account_security  : numero/email verifies, echecs de connexion, verrouillage
  - academy_trusted_devices   : appareils reconnus (jeton stocke hache)
  - academy_security_events   : journal d'audit (connexions, codes, verrouillages)

Revision ID: 0006_security_verification
Revises: 0005_academy_countries
"""
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.db.migration_utils import create_index_if_missing, create_table_if_missing

revision = "0006_security_verification"
down_revision = "0005_academy_countries"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    create_table_if_missing(
        "academy_verifications",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),  # signup | login | password_reset
        sa.Column("role", sa.String(20), nullable=True),  # apprenant | client | admin
        sa.Column("account_id", BIGINT_U, nullable=True),
        sa.Column("channel", sa.String(12), nullable=False),  # whatsapp | sms | email
        sa.Column("destination", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("uq_academy_verifications_request", "academy_verifications", ["request_id"], unique=True)
    create_index_if_missing("ix_academy_verifications_dest", "academy_verifications", ["destination", "created_at"])
    create_index_if_missing("ix_academy_verifications_ip", "academy_verifications", ["ip", "created_at"])
    create_index_if_missing("ix_academy_verifications_account", "academy_verifications", ["role", "account_id", "purpose"])

    create_table_if_missing(
        "academy_account_security",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("account_id", BIGINT_U, nullable=False),
        sa.Column("phone_verified_at", sa.DateTime(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lock_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_ip", sa.String(45), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("uq_academy_account_security_account", "academy_account_security", ["role", "account_id"], unique=True)

    create_table_if_missing(
        "academy_trusted_devices",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("account_id", BIGINT_U, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    create_index_if_missing("uq_academy_trusted_devices_token", "academy_trusted_devices", ["token_hash"], unique=True)
    create_index_if_missing("ix_academy_trusted_devices_account", "academy_trusted_devices", ["role", "account_id"])

    create_table_if_missing(
        "academy_security_events",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("role", sa.String(20), nullable=True),
        sa.Column("account_id", BIGINT_U, nullable=True),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(12), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("detail", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("ix_academy_security_events_account", "academy_security_events", ["role", "account_id", "created_at"])
    create_index_if_missing("ix_academy_security_events_ip", "academy_security_events", ["ip", "created_at"])
    create_index_if_missing("ix_academy_security_events_created", "academy_security_events", ["created_at"])


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de donnees de production.
    pass
