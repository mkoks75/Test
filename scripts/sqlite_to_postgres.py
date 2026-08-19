#!/usr/bin/env python3
"""Zet de bestaande SQLite-database om naar SQL voor PostgreSQL.

Gebruik op de server (of lokaal met een kopie van de database):

    python3 scripts/sqlite_to_postgres.py data/voorraad.db > import.sql
    psql "$DATABASE_URL" -f db/migrations/0001_init.sql
    psql "$DATABASE_URL" -f import.sql

De id's worden één op één overgenomen zodat historie, verwijzingen en
volgnummers exact kloppen. Na de import worden alle sequences bijgezet zodat
nieuwe records verdergaan waar de oude applicatie stopte.

Het script is idempotent te gebruiken: het begint met TRUNCATE van de
doeltabellen, zodat een tweede import geen dubbele rijen oplevert.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime

# Volgorde is belangrijk: ouders vóór kinderen.
TABELLEN = [
    "users",
    "password_reset_tokens",
    "eenheden",
    "products",
    "locations",
    "conserveringsmethoden",
    "ontvangers",
    "product_houdbaarheid",
    "harvest_entries",
    "uitgiftes",
    "shop_items",
    "containers",
    "niveau_logs",
    "shop_uitgiftes",
    "shared_lists",
    "product_cache",
]


def quote(waarde: object) -> str:
    if waarde is None:
        return "NULL"
    if isinstance(waarde, bool):
        return "TRUE" if waarde else "FALSE"
    if isinstance(waarde, (int, float)):
        return repr(waarde)
    if isinstance(waarde, (bytes, bytearray)):
        return "'\\x" + waarde.hex() + "'"
    if isinstance(waarde, (datetime, date)):
        return "'" + waarde.isoformat() + "'"
    return "'" + str(waarde).replace("'", "''") + "'"


BOOLEAN_KOLOMMEN = {
    "used",
    "etiket_per_stuk",
    "actief",
    "active",
    "uitgegeven",
    "is_deelbaar",
    "opslag_in_container",
    "is_admin",
}


def normaliseer(kolom: str, waarde: object) -> object:
    """SQLite bewaart booleans als 0/1; PostgreSQL wil echte booleans."""
    if kolom in BOOLEAN_KOLOMMEN and isinstance(waarde, int):
        return bool(waarde)
    return waarde


def bestaande_tabellen(verbinding: sqlite3.Connection) -> set[str]:
    rijen = verbinding.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {rij[0] for rij in rijen}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 1

    verbinding = sqlite3.connect(sys.argv[1])
    verbinding.row_factory = sqlite3.Row
    aanwezig = bestaande_tabellen(verbinding)

    uit = sys.stdout
    uit.write("-- Gegenereerd door scripts/sqlite_to_postgres.py\n")
    uit.write("BEGIN;\n")
    uit.write("SET session_replication_role = replica;\n\n")

    te_doen = [tabel for tabel in TABELLEN if tabel in aanwezig]
    uit.write(
        "TRUNCATE " + ", ".join(reversed(te_doen)) + " RESTART IDENTITY CASCADE;\n\n"
    )

    for tabel in te_doen:
        rijen = verbinding.execute(f"SELECT * FROM {tabel}").fetchall()
        if not rijen:
            uit.write(f"-- {tabel}: geen rijen\n\n")
            continue

        kolommen = list(rijen[0].keys())
        kolomlijst = ", ".join(f'"{kolom}"' for kolom in kolommen)
        uit.write(f"-- {tabel}: {len(rijen)} rijen\n")

        for rij in rijen:
            waarden = ", ".join(
                quote(normaliseer(kolom, rij[kolom])) for kolom in kolommen
            )
            uit.write(f"INSERT INTO {tabel} ({kolomlijst}) VALUES ({waarden});\n")
        uit.write("\n")

    uit.write("SET session_replication_role = DEFAULT;\n\n")
    uit.write("-- Sequences bijzetten zodat nieuwe id's niet botsen\n")
    for tabel in te_doen:
        uit.write(
            "SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
            "COALESCE((SELECT MAX(id) FROM {t}), 1), "
            "(SELECT MAX(id) IS NOT NULL FROM {t}));\n".format(t=tabel)
        )

    uit.write("\nCOMMIT;\n")
    verbinding.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
