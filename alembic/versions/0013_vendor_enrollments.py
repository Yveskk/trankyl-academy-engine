"""Dossier d'enrolement des prestataires (table partagee avec le backend Trankyl et son admin Angular).

Additif et idempotent : en production la table existe deja (creee par le backend Node / Prisma) et n'est pas touchee ;
sur une base qui ne l'a pas encore (ex. la base de developpement), elle est creee avec EXACTEMENT les memes colonnes.

Revision ID: 0013_vendor_enrollments
Revises: 0012_quote_requests
"""
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.db.migration_utils import create_index_if_missing, create_table_if_missing

revision = "0013_vendor_enrollments"
down_revision = "0012_quote_requests"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)


def _flag(name: str) -> sa.Column:
    return sa.Column(name, mysql.TINYINT(), nullable=True, server_default=sa.text("0"))


def upgrade() -> None:
    created = create_table_if_missing(
        "vendor_enrollments",
        sa.Column("enroll_id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("enroll_vendor_id", BIGINT_U, nullable=False),
        sa.Column("enroll_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("enroll_name", sa.String(255)), sa.Column("enroll_family_name", sa.String(255)), sa.Column("enroll_sex", sa.String(10)),
        sa.Column("enroll_dob", sa.String(50)), sa.Column("enroll_phone", sa.String(50)), sa.Column("enroll_email", sa.String(255)),
        sa.Column("enroll_address", mysql.MEDIUMTEXT()), sa.Column("enroll_city", sa.String(255)), sa.Column("enroll_country", sa.String(255)),
        sa.Column("enroll_geolocation", sa.String(255)), sa.Column("enroll_bio", mysql.MEDIUMTEXT()),
        _flag("enroll_is_professional"), _flag("enroll_is_expert"), _flag("enroll_if_company"),
        sa.Column("enroll_company_name", sa.String(255)), sa.Column("enroll_study_level", sa.String(255)), sa.Column("enroll_languages", sa.String(255)),
        sa.Column("enroll_id_number", sa.String(255)), sa.Column("enroll_id_file", mysql.MEDIUMTEXT()), sa.Column("enroll_diploma_file", mysql.MEDIUMTEXT()),
        sa.Column("enroll_cv_file", mysql.MEDIUMTEXT()), sa.Column("enroll_photo", mysql.MEDIUMTEXT()),
        *[_flag(f"approve_{n}") for n in (
            "name", "family_name", "sex", "dob", "phone", "email", "address", "city", "country", "bio", "is_professional", "is_expert", "if_company",
            "company_name", "study_level", "languages", "id_number", "id_file", "diploma_file", "cv_file", "photo", "geolocation")],
        sa.Column("admin_notes", mysql.MEDIUMTEXT()),
        sa.Column("enroll_created_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("enroll_updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("enroll_company_sector", sa.String(100)), sa.Column("enroll_company_type", sa.String(50)), sa.Column("enroll_custom_language", sa.String(255)),
        sa.Column("enroll_id_type", sa.String(50)), sa.Column("enroll_id_file_verso", sa.Text()), sa.Column("enroll_rc_file", sa.Text()),
        sa.Column("enroll_diploma_files", mysql.LONGTEXT()), sa.Column("enroll_cv_files", mysql.LONGTEXT()), sa.Column("enroll_signature", mysql.LONGTEXT()),
        sa.Column("enroll_signature_pending", mysql.LONGTEXT()), sa.Column("enroll_signature_reason", sa.String(500)), sa.Column("enroll_signature_pending_at", sa.DateTime()),
        sa.Column("enroll_admin_note", sa.Text()), sa.Column("enroll_casier_file", sa.Text()), sa.Column("enroll_contract_pdf", sa.Text()), sa.Column("enroll_cef_files", mysql.LONGTEXT()),
    )
    if created:
        create_index_if_missing("idx_enroll_vendor", "vendor_enrollments", ["enroll_vendor_id"])


def downgrade() -> None:
    pass
