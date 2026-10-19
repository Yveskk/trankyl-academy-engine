"""Donnees prestataire absentes de `vendors` : profil enrichi, medias,
disponibilites, et moderation des avis.

Additif uniquement :
  - academy_provider_profiles     (nouvelle) : 1 ligne par prestataire
  - academy_provider_media        (nouvelle) : realisations (photo/video/avant-apres)
  - academy_provider_availability (nouvelle) : plages hebdomadaires
  - academy_reviews : + booking_id, status, reply, replied_at, criteria_json, source
    (les avis existants deviennent status='approved', source='academy')

Revision ID: 0003_provider_extras
Revises: 0002_home_configuration
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from app.db.migration_utils import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "0003_provider_extras"
down_revision = "0002_home_configuration"
branch_labels = None
depends_on = None

BIGINT_U = mysql.BIGINT(unsigned=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    # --- academy_reviews : moderation + reponse du prestataire --------------
    add_column_if_missing("academy_reviews", sa.Column("booking_id", BIGINT_U, nullable=True))
    add_column_if_missing("academy_reviews", sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'approved'")))
    add_column_if_missing("academy_reviews", sa.Column("reply", sa.Text(), nullable=True))
    add_column_if_missing("academy_reviews", sa.Column("replied_at", sa.DateTime(), nullable=True))
    add_column_if_missing("academy_reviews", sa.Column("criteria_json", sa.Text(), nullable=True))
    add_column_if_missing("academy_reviews", sa.Column("source", sa.String(30), nullable=False, server_default=sa.text("'academy'")))
    # (source, booking_id) unique : rend l'import depuis booking_marks idempotent.
    # booking_id NULL autorise plusieurs lignes (avis sans reservation).
    create_index_if_missing("uq_academy_reviews_source_booking", "academy_reviews", ["source", "booking_id"], unique=True)
    create_index_if_missing("ix_academy_reviews_status", "academy_reviews", ["vendor_id", "status"])

    # --- academy_provider_profiles ----------------------------------------
    create_table_if_missing(
        "academy_provider_profiles",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("vendor_id", BIGINT_U, sa.ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False),
        sa.Column("headline", sa.String(255), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("about_en", sa.Text(), nullable=True),
        sa.Column("cover_image_url", sa.String(500), nullable=True),
        sa.Column("response_time_minutes", sa.Integer(), nullable=True),
        sa.Column("on_time_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("is_insured", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_address_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        # NULL = automatique (regle), 1 = force "Top prestataire", 0 = exclu
        sa.Column("top_override", sa.SmallInteger(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("featured_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("public_slug", sa.String(150), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("uq_academy_provider_profiles_vendor", "academy_provider_profiles", ["vendor_id"], unique=True)
    create_index_if_missing("uq_academy_provider_profiles_slug", "academy_provider_profiles", ["public_slug"], unique=True)
    create_index_if_missing("ix_academy_provider_profiles_featured", "academy_provider_profiles", ["is_featured", "featured_order"])

    # --- academy_provider_media -------------------------------------------
    create_table_if_missing(
        "academy_provider_media",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("vendor_id", BIGINT_U, sa.ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default=sa.text("'photo'")),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("thumb_url", sa.String(500), nullable=True),
        sa.Column("caption", sa.String(255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("ix_academy_provider_media_vendor", "academy_provider_media", ["vendor_id", "is_active", "sort_order"])

    # --- academy_provider_availability ------------------------------------
    create_table_if_missing(
        "academy_provider_availability",
        sa.Column("id", BIGINT_U, primary_key=True, autoincrement=True),
        sa.Column("vendor_id", BIGINT_U, sa.ForeignKey("vendors.vendor_id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),  # 0 = lundi ... 6 = dimanche
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    create_index_if_missing("ix_academy_provider_availability_vendor", "academy_provider_availability", ["vendor_id", "weekday", "is_active"])


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de donnees de production.
    pass
