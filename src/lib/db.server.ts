/**
 * Databaseverbinding met PostgreSQL op de eigen server.
 *
 * Server-only: dit bestand mag nooit vanuit een component of route worden
 * geïmporteerd. Server functions importeren het binnen hun handler, of
 * indirect via een *.server.ts query-module.
 *
 * De verbinding wordt lui opgebouwd en hergebruikt, zodat er per proces één
 * pool bestaat en `DATABASE_URL` pas bij het eerste gebruik gelezen wordt
 * (environment wordt per request geïnjecteerd).
 */

import postgres from "postgres";

let verbinding: postgres.Sql | null = null;

export class DatabaseNietGeconfigureerd extends Error {
  constructor() {
    super(
      "DATABASE_URL ontbreekt. Zet de verbinding met PostgreSQL in de omgevingsvariabelen.",
    );
    this.name = "DatabaseNietGeconfigureerd";
  }
}

export function db(): postgres.Sql {
  if (verbinding) return verbinding;

  const url = process.env["DATABASE_URL"];
  if (!url) throw new DatabaseNietGeconfigureerd();

  verbinding = postgres(url, {
    max: Number(process.env["DATABASE_POOL_SIZE"] ?? 10),
    idle_timeout: 30,
    connect_timeout: 10,
    // Datums als tekst teruggeven; de applicatie werkt met ISO-strings.
    types: {
      date: {
        to: 1082,
        from: [1082],
        serialize: (waarde: string) => waarde,
        parse: (waarde: string) => waarde,
      },
    },
    onnotice: () => {},
  });

  return verbinding;
}

/** Is er een database geconfigureerd? Handig voor duidelijke foutmeldingen. */
export function heeftDatabase(): boolean {
  return Boolean(process.env["DATABASE_URL"]);
}
