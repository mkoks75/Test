#!/usr/bin/env node
/**
 * Migratierunner. Draait alle .sql-bestanden uit db/migrations op volgorde
 * en houdt in de tabel schema_migrations bij wat al gedraaid heeft.
 *
 * Wordt aangeroepen bij het starten van de container, vóór de webserver:
 *   node scripts/migrate.mjs
 */

import { readdir, readFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import postgres from "postgres";

const hier = dirname(fileURLToPath(import.meta.url));
const migratieMap = join(hier, "..", "db", "migrations");

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL ontbreekt — migraties overgeslagen.");
  process.exit(1);
}

const sql = postgres(url, { max: 1, onnotice: () => {} });

try {
  await sql`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      naam       TEXT PRIMARY KEY,
      gedraaid_op TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;

  const gedraaid = new Set(
    (await sql`SELECT naam FROM schema_migrations`).map((rij) => rij.naam),
  );

  const bestanden = (await readdir(migratieMap))
    .filter((naam) => naam.endsWith(".sql"))
    .sort();

  let aantal = 0;
  for (const bestand of bestanden) {
    if (gedraaid.has(bestand)) continue;

    const inhoud = await readFile(join(migratieMap, bestand), "utf8");
    console.log(`→ migratie ${bestand}`);
    await sql.unsafe(inhoud);
    await sql`INSERT INTO schema_migrations (naam) VALUES (${bestand})`;
    aantal += 1;
  }

  console.log(
    aantal === 0 ? "Database is bij." : `${aantal} migratie(s) uitgevoerd.`,
  );
} catch (fout) {
  console.error("Migratie mislukt:", fout);
  process.exitCode = 1;
} finally {
  await sql.end();
}
