"""Helpers pour des migrations ADDITIVES et idempotentes.

Regle du projet : la base MySQL est partagee avec le site/l'app Trankyl et
contient des donnees de production. Une migration ne supprime, ne renomme et
ne retype JAMAIS rien d'existant. Elle ne fait que creer ce qui manque
(tables, colonnes, index), et chaque operation verifie d'abord si l'objet
existe deja, pour pouvoir etre rejouee sans risque."""
import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    return _inspector().has_table(table)


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def has_index(table: str, index: str) -> bool:
    if not has_table(table):
        return False
    return index in {i["name"] for i in _inspector().get_indexes(table)}


def add_column_if_missing(table: str, column: sa.Column) -> None:
    if has_column(table, column.name):
        return
    op.add_column(table, column)


def create_index_if_missing(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if has_index(table, name):
        return
    op.create_index(name, table, columns, unique=unique)


def create_table_if_missing(name: str, *columns, **kwargs) -> bool:
    """Cree la table si elle n'existe pas. Retourne True si elle a ete creee."""
    if has_table(name):
        return False
    op.create_table(name, *columns, **kwargs)
    return True
