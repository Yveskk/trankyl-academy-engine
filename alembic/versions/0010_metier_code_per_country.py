"""Un meme code de metier peut exister dans chaque pays.

Additif cote donnees (aucune ligne modifiee). Le code du metier n'est plus unique globalement
mais par pays : l'index unique sur `code` est remplace par un index unique (country_code, code)
et un index simple sur `code` pour les recherches.

Revision ID: 0010_metier_code_per_country
Revises: 0009_role_countries
"""
import sqlalchemy as sa
from alembic import op

from app.db.migration_utils import create_index_if_missing, has_index, has_table

revision = "0010_metier_code_per_country"
down_revision = "0009_role_countries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("academy_metiers"):
        return
    # Cree d'abord les nouveaux index (jamais une fenetre sans index), puis retire l'ancien unique sur `code`.
    create_index_if_missing("ux_academy_metiers_country_code", "academy_metiers", ["country_code", "code"], unique=True)
    if has_index("academy_metiers", "ix_academy_metiers_code"):
        insp = sa.inspect(op.get_bind())
        old = next((i for i in insp.get_indexes("academy_metiers") if i["name"] == "ix_academy_metiers_code"), None)
        if old and old["unique"] and old["column_names"] == ["code"]:
            op.get_bind().execute(sa.text("ALTER TABLE `academy_metiers` DROP INDEX `ix_academy_metiers_code`"))
    create_index_if_missing("ix_academy_metiers_code", "academy_metiers", ["code"])


def downgrade() -> None:
    pass
