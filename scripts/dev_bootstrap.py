"""Rend la base DEV (trankyln_dev_db) comparable a la production, pour pouvoir
tester les migrations Academy. Ne fait que de l'ajout de colonnes manquantes
sur les tables du coeur Trankyl (ces colonnes existent deja en prod) et
REFUSE de tourner sur autre chose qu'une base dont le nom finit par `_dev_db`.

Usage : python -m scripts.dev_bootstrap
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

from sqlalchemy import create_engine, inspect, text  # noqa: E402

url = os.environ["DATABASE_URL"]
db_name = url.rsplit("/", 1)[-1].split("?")[0]
if not db_name.endswith("_dev_db"):
    sys.exit(f"Refus : '{db_name}' n'est pas une base dev (nom attendu : *_dev_db).")

engine = create_engine(url)

# (table, colonne, DDL de la colonne) : presentes en prod, absentes en dev.
CORE_COLUMNS = [
    ("vendors", "vendor_slug", "VARCHAR(255) NULL"),
    ("vendors", "vendor_referral_code", "VARCHAR(255) NULL"),
    ("events", "event_category", "VARCHAR(191) NULL"),
    ("clients", "client_referral_code", "VARCHAR(255) NULL"),
]

with engine.begin() as conn:
    insp = inspect(conn)
    for table, column, ddl in CORE_COLUMNS:
        existing = {c["name"] for c in insp.get_columns(table)}
        if column in existing:
            print(f"= {table}.{column} deja present")
            continue
        conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}"))
        print(f"+ {table}.{column} ajoute")
print(f"Base dev '{db_name}' prete.")
