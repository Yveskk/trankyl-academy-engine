"""Details de profil public d'un prestataire utilises par la recherche et la
page profil : frais de deplacement, experience, zone d'intervention, note de
bas de tableau des prix.

Additif uniquement (colonnes NULL sur academy_provider_profiles, creee en 0003).

Revision ID: 0004_provider_profile_details
Revises: 0003_provider_extras
"""
import sqlalchemy as sa

from app.db.migration_utils import add_column_if_missing

revision = "0004_provider_profile_details"
down_revision = "0003_provider_extras"
branch_labels = None
depends_on = None

T = "academy_provider_profiles"


def upgrade() -> None:
    add_column_if_missing(T, sa.Column("visit_fee", sa.Integer(), nullable=True))
    add_column_if_missing(T, sa.Column("years_experience", sa.Integer(), nullable=True))
    add_column_if_missing(T, sa.Column("service_radius_km", sa.Integer(), nullable=True))
    add_column_if_missing(T, sa.Column("zone_label", sa.String(255), nullable=True))
    add_column_if_missing(T, sa.Column("services_note", sa.Text(), nullable=True))
    add_column_if_missing(T, sa.Column("services_note_en", sa.Text(), nullable=True))


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de donnees de production.
    pass
