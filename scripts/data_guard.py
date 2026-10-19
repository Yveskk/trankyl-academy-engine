"""Filet de securite "zero perte de donnees" autour d'une migration.

  python -m scripts.data_guard snapshot avant.json   # AVANT la migration
  python -m scripts.data_guard verify   avant.json   # APRES la migration

`snapshot` enregistre, pour CHAQUE table de la base, ses colonnes, son nombre
de lignes et l'empreinte (md5) de chaque ligne indexee par cle primaire.
`verify` rejoue le calcul avec les colonnes d'origine seulement : toute ligne
disparue, ajoutee ou modifiee, toute colonne supprimee ou table manquante est
signalee, et la commande sort en erreur (code 1). Les colonnes/tables AJOUTEES
par la migration sont ignorees (c'est le but d'une migration additive).

Lecture seule : n'ecrit rien en base."""
import hashlib
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

from sqlalchemy import create_engine, inspect, text  # noqa: E402

# Table de suivi d'Alembic : sa ligne change a chaque migration, par construction.
IGNORED_TABLES = {"alembic_version"}


def _row_hash(values) -> str:
    return hashlib.md5("\x1f".join("\x00NULL" if v is None else str(v) for v in values).encode()).hexdigest()


def _table_state(conn, table: str, columns: list[str]) -> dict:
    insp = inspect(conn)
    pk = insp.get_pk_constraint(table).get("constrained_columns") or []
    cols_sql = ", ".join(f"`{c}`" for c in columns)
    rows = conn.execute(text(f"SELECT {cols_sql} FROM `{table}`")).fetchall()
    idx = [columns.index(c) for c in pk if c in columns]
    hashes: dict[str, str] = {}
    for n, row in enumerate(rows):
        key = "|".join(str(row[i]) for i in idx) if idx else f"#{n}"
        h = _row_hash(row)
        # table sans cle primaire : on compte les doublons de lignes identiques
        if not idx:
            key = f"{h}#{sum(1 for k in hashes if k.startswith(h))}"
        hashes[key] = h
    return {"rows": len(rows), "hashes": hashes}


def snapshot(path: str) -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    out: dict = {}
    with engine.connect() as conn:
        insp = inspect(conn)
        for table in sorted(t for t in insp.get_table_names() if t not in IGNORED_TABLES):
            columns = [c["name"] for c in insp.get_columns(table)]
            state = _table_state(conn, table, columns)
            out[table] = {"columns": columns, **state}
    json.dump(out, open(path, "w"))
    total = sum(t["rows"] for t in out.values())
    print(f"Snapshot : {len(out)} tables, {total} lignes -> {path}")


def verify(path: str) -> int:
    before = json.load(open(path))
    engine = create_engine(os.environ["DATABASE_URL"])
    problems: list[str] = []
    new_rows_info: list[str] = []
    with engine.connect() as conn:
        insp = inspect(conn)
        tables_now = set(insp.get_table_names())
        for table, b in before.items():
            if table in IGNORED_TABLES:
                continue
            if table not in tables_now:
                problems.append(f"TABLE DISPARUE : {table}")
                continue
            cols_now = {c["name"] for c in insp.get_columns(table)}
            missing_cols = [c for c in b["columns"] if c not in cols_now]
            if missing_cols:
                problems.append(f"COLONNES DISPARUES : {table}.{missing_cols}")
                continue
            now = _table_state(conn, table, b["columns"])
            lost = [k for k in b["hashes"] if k not in now["hashes"]]
            changed = [k for k, h in b["hashes"].items() if k in now["hashes"] and now["hashes"][k] != h]
            added = [k for k in now["hashes"] if k not in b["hashes"]]
            if lost:
                problems.append(f"LIGNES PERDUES : {table} ({len(lost)}) ex. {lost[:3]}")
            if changed:
                problems.append(f"LIGNES MODIFIEES : {table} ({len(changed)}) ex. {changed[:3]}")
            if added:
                new_rows_info.append(f"{table}: +{len(added)} ligne(s) (information, pas une perte)")
        created = sorted(tables_now - set(before))
    print(f"Tables verifiees : {len(before)} | tables creees depuis : {len(created)} {created}")
    for line in new_rows_info:
        print("  ~", line)
    if problems:
        print("\nECHEC :")
        for p in problems:
            print("  !", p)
        return 1
    print("OK : aucune ligne perdue ni modifiee, aucune colonne supprimee.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("snapshot", "verify"):
        sys.exit(__doc__)
    if sys.argv[1] == "snapshot":
        snapshot(sys.argv[2])
    else:
        sys.exit(verify(sys.argv[2]))
