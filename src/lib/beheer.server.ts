/**
 * Beheer van de stamdata (producten, locaties, eenheden,
 * conserveringsmethoden, ontvangers en houdbaarheidstermijnen). Server-only.
 *
 * De tabellen komen één op één uit de oude applicatie; kolomnamen verschillen
 * per tabel (name/active versus naam/actief), daarom is er per soort een
 * expliciete query in plaats van één generieke.
 */

import { db } from "./db.server";

export type BeheerItem = { id: number; naam: string; actief: boolean };

export type BeheerData = {
  producten: Array<BeheerItem & { eenheidId: number | null; eenheid: string | null }>;
  locaties: BeheerItem[];
  eenheden: Array<BeheerItem & { perStuk: boolean }>;
  conserveringsmethoden: BeheerItem[];
  ontvangers: BeheerItem[];
  houdbaarheid: Array<{
    id: number;
    productId: number;
    product: string;
    conserveringId: number | null;
    conservering: string | null;
    maanden: number;
    actief: boolean;
  }>;
};

export type Soort =
  | "product"
  | "locatie"
  | "eenheid"
  | "conservering"
  | "ontvanger";

export async function haalBeheerData(): Promise<BeheerData> {
  const sql = db();

  const [producten, locaties, eenheden, methoden, ontvangers, houdbaarheid] =
    await Promise.all([
      sql<
        Array<{
          id: number;
          name: string;
          active: boolean;
          eenheid_id: number | null;
          eenheid: string | null;
        }>
      >`
        SELECT p.id, p.name, p.active, p.eenheid_id, e.naam AS eenheid
        FROM products p
        LEFT JOIN eenheden e ON e.id = p.eenheid_id
        ORDER BY p.name
      `,
      sql<Array<{ id: number; name: string; active: boolean }>>`
        SELECT id, name, active FROM locations ORDER BY name
      `,
      sql<
        Array<{ id: number; naam: string; actief: boolean; etiket_per_stuk: boolean }>
      >`
        SELECT id, naam, actief, etiket_per_stuk FROM eenheden ORDER BY naam
      `,
      sql<Array<{ id: number; naam: string; actief: boolean }>>`
        SELECT id, naam, actief FROM conserveringsmethoden ORDER BY naam
      `,
      sql<Array<{ id: number; naam: string; actief: boolean }>>`
        SELECT id, naam, actief FROM ontvangers ORDER BY naam
      `,
      sql<
        Array<{
          id: number;
          product_id: number;
          product: string;
          conserveringsmethode_id: number | null;
          conservering: string | null;
          houdbaarheid_maanden: number;
          actief: boolean;
        }>
      >`
        SELECT h.id, h.product_id, p.name AS product,
               h.conserveringsmethode_id, c.naam AS conservering,
               h.houdbaarheid_maanden, h.actief
        FROM product_houdbaarheid h
        JOIN products p ON p.id = h.product_id
        LEFT JOIN conserveringsmethoden c ON c.id = h.conserveringsmethode_id
        ORDER BY p.name, c.naam NULLS FIRST
      `,
    ]);

  return {
    producten: producten.map((p) => ({
      id: p.id,
      naam: p.name,
      actief: p.active,
      eenheidId: p.eenheid_id,
      eenheid: p.eenheid,
    })),
    locaties: locaties.map((l) => ({ id: l.id, naam: l.name, actief: l.active })),
    eenheden: eenheden.map((e) => ({
      id: e.id,
      naam: e.naam,
      actief: e.actief,
      perStuk: e.etiket_per_stuk,
    })),
    conserveringsmethoden: methoden,
    ontvangers,
    houdbaarheid: houdbaarheid.map((h) => ({
      id: h.id,
      productId: h.product_id,
      product: h.product,
      conserveringId: h.conserveringsmethode_id,
      conservering: h.conservering,
      maanden: Number(h.houdbaarheid_maanden),
      actief: h.actief,
    })),
  };
}

export async function voegStamdataToe(
  soort: Soort,
  naam: string,
  eenheidId: number | null,
): Promise<{ id: number }> {
  const sql = db();
  let rijen: Array<{ id: number }> = [];

  switch (soort) {
    case "product":
      rijen = await sql`
        INSERT INTO products (name, eenheid_id, active)
        VALUES (${naam}, ${eenheidId}, TRUE) RETURNING id
      `;
      break;
    case "locatie":
      rijen = await sql`
        INSERT INTO locations (name, active) VALUES (${naam}, TRUE) RETURNING id
      `;
      break;
    case "eenheid":
      rijen = await sql`
        INSERT INTO eenheden (naam, actief) VALUES (${naam}, TRUE) RETURNING id
      `;
      break;
    case "conservering":
      rijen = await sql`
        INSERT INTO conserveringsmethoden (naam, actief)
        VALUES (${naam}, TRUE) RETURNING id
      `;
      break;
    case "ontvanger":
      rijen = await sql`
        INSERT INTO ontvangers (naam, actief) VALUES (${naam}, TRUE) RETURNING id
      `;
      break;
  }

  return { id: rijen[0]?.id ?? 0 };
}

export async function wijzigStamdata(
  soort: Soort,
  id: number,
  naam: string,
  actief: boolean,
): Promise<{ ok: true }> {
  const sql = db();

  switch (soort) {
    case "product":
      await sql`UPDATE products SET name = ${naam}, active = ${actief} WHERE id = ${id}`;
      break;
    case "locatie":
      await sql`UPDATE locations SET name = ${naam}, active = ${actief} WHERE id = ${id}`;
      break;
    case "eenheid":
      await sql`UPDATE eenheden SET naam = ${naam}, actief = ${actief} WHERE id = ${id}`;
      break;
    case "conservering":
      await sql`UPDATE conserveringsmethoden SET naam = ${naam}, actief = ${actief} WHERE id = ${id}`;
      break;
    case "ontvanger":
      await sql`UPDATE ontvangers SET naam = ${naam}, actief = ${actief} WHERE id = ${id}`;
      break;
  }

  return { ok: true };
}

export async function bewaarHoudbaarheid(invoer: {
  productId: number;
  conserveringId: number | null;
  maanden: number;
}): Promise<{ ok: true }> {
  const sql = db();

  const bestaand = await sql<Array<{ id: number }>>`
    SELECT id FROM product_houdbaarheid
    WHERE product_id = ${invoer.productId}
      AND conserveringsmethode_id IS NOT DISTINCT FROM ${invoer.conserveringId}
    LIMIT 1
  `;

  if (bestaand[0]) {
    await sql`
      UPDATE product_houdbaarheid
      SET houdbaarheid_maanden = ${invoer.maanden}, actief = TRUE
      WHERE id = ${bestaand[0].id}
    `;
  } else {
    await sql`
      INSERT INTO product_houdbaarheid
        (product_id, conserveringsmethode_id, houdbaarheid_maanden, actief)
      VALUES (${invoer.productId}, ${invoer.conserveringId}, ${invoer.maanden}, TRUE)
    `;
  }

  return { ok: true };
}
