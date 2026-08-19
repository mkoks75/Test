/**
 * Query's op de voorraad. Server-only.
 *
 * Alles wat hier teruggegeven wordt is een simpel object met ISO-datums en
 * getallen, zodat het zonder omwegen door een server function heen kan.
 */

import { db } from "./db.server";
import { vandaag } from "./datum";

export type Stamdata = {
  producten: Array<{ id: number; naam: string; eenheid: string }>;
  locaties: Array<{ id: number; naam: string }>;
  conserveringsmethoden: Array<{ id: number; naam: string }>;
  bewaartermijnen: Array<{
    productId: number;
    conserveringId: number | null;
    maanden: number;
  }>;
  eenheidPerStuk: Record<number, boolean>;
};

export async function haalStamdata(): Promise<Stamdata> {
  const sql = db();

  const [producten, locaties, methoden, termijnen] = await Promise.all([
    sql<
      Array<{ id: number; name: string; eenheid: string | null; per_stuk: boolean | null }>
    >`
      SELECT p.id, p.name, COALESCE(e.naam, p.unit) AS eenheid, e.etiket_per_stuk AS per_stuk
      FROM products p
      LEFT JOIN eenheden e ON e.id = p.eenheid_id
      WHERE p.active
      ORDER BY p.name
    `,
    sql<Array<{ id: number; name: string }>>`
      SELECT id, name FROM locations WHERE active ORDER BY name
    `,
    sql<Array<{ id: number; naam: string }>>`
      SELECT id, naam FROM conserveringsmethoden WHERE actief ORDER BY naam
    `,
    sql<
      Array<{
        product_id: number;
        conserveringsmethode_id: number | null;
        houdbaarheid_maanden: number;
      }>
    >`
      SELECT product_id, conserveringsmethode_id, houdbaarheid_maanden
      FROM product_houdbaarheid
      WHERE actief
    `,
  ]);

  const eenheidPerStuk: Record<number, boolean> = {};
  for (const p of producten) eenheidPerStuk[p.id] = Boolean(p.per_stuk);

  return {
    producten: producten.map((p) => ({
      id: p.id,
      naam: p.name,
      eenheid: p.eenheid ?? "",
    })),
    locaties: locaties.map((l) => ({ id: l.id, naam: l.name })),
    conserveringsmethoden: methoden,
    bewaartermijnen: termijnen.map((t) => ({
      productId: t.product_id,
      conserveringId: t.conserveringsmethode_id,
      maanden: t.houdbaarheid_maanden,
    })),
    eenheidPerStuk,
  };
}

export type DashboardData = {
  peildatum: string;
  cijfers: {
    productenInVoorraad: number;
    partijen: number;
    kortHoudbaar: number;
    verlopen: number;
    dezeMaand: number;
  };
  bijnaVerlopen: Array<{
    id: number;
    product: string;
    locatie: string;
    conservering: string;
    hoeveelheid: number;
    eenheid: string;
    houdbaarTot: string;
  }>;
  totalen: Array<{
    sleutel: string;
    product: string;
    conservering: string;
    eenheid: string;
    totaal: number;
    locaties: number;
  }>;
};

export async function haalDashboard(): Promise<DashboardData> {
  const sql = db();
  const peildatum = vandaag();
  const maandStart = `${peildatum.slice(0, 7)}-01`;

  const [cijfers, verloopt, totalen] = await Promise.all([
    sql<
      Array<{
        producten: number;
        partijen: number;
        kort: number;
        verlopen: number;
        deze_maand: number;
      }>
    >`
      SELECT
        COUNT(DISTINCT product_id)                                        AS producten,
        COUNT(*)                                                          AS partijen,
        COUNT(*) FILTER (
          WHERE houdbaar_tot IS NOT NULL
            AND houdbaar_tot >= ${peildatum}::date
            AND houdbaar_tot <= ${peildatum}::date + 14
        )                                                                 AS kort,
        COUNT(*) FILTER (
          WHERE houdbaar_tot IS NOT NULL AND houdbaar_tot < ${peildatum}::date
        )                                                                 AS verlopen,
        COUNT(*) FILTER (WHERE date >= ${maandStart})                     AS deze_maand
      FROM harvest_entries
      WHERE NOT uitgegeven
    `,
    sql<
      Array<{
        id: number;
        product: string;
        locatie: string;
        conservering: string | null;
        quantity: number;
        eenheid: string | null;
        houdbaar_tot: string;
      }>
    >`
      SELECT h.id,
             p.name AS product,
             l.name AS locatie,
             c.naam AS conservering,
             h.quantity,
             COALESCE(e.naam, p.unit) AS eenheid,
             h.houdbaar_tot
      FROM harvest_entries h
      JOIN products  p ON p.id = h.product_id
      JOIN locations l ON l.id = h.location_id
      LEFT JOIN conserveringsmethoden c ON c.id = h.conserveringsmethode_id
      LEFT JOIN eenheden e ON e.id = p.eenheid_id
      WHERE NOT h.uitgegeven
        AND h.houdbaar_tot IS NOT NULL
        AND h.houdbaar_tot <= ${peildatum}::date + 14
      ORDER BY h.houdbaar_tot ASC
      LIMIT 40
    `,
    sql<
      Array<{
        product_id: number;
        product: string;
        conservering: string | null;
        eenheid: string | null;
        totaal: number;
        locaties: number;
      }>
    >`
      SELECT p.id AS product_id,
             p.name AS product,
             c.naam AS conservering,
             COALESCE(e.naam, p.unit) AS eenheid,
             SUM(h.quantity)::double precision AS totaal,
             COUNT(DISTINCT h.location_id)::int AS locaties
      FROM harvest_entries h
      JOIN products p ON p.id = h.product_id
      LEFT JOIN conserveringsmethoden c ON c.id = h.conserveringsmethode_id
      LEFT JOIN eenheden e ON e.id = p.eenheid_id
      WHERE NOT h.uitgegeven
      GROUP BY p.id, p.name, c.naam, COALESCE(e.naam, p.unit)
      HAVING SUM(h.quantity) > 0
      ORDER BY p.name, c.naam NULLS FIRST
    `,
  ]);

  const c = cijfers[0];

  return {
    peildatum,
    cijfers: {
      productenInVoorraad: Number(c?.producten ?? 0),
      partijen: Number(c?.partijen ?? 0),
      kortHoudbaar: Number(c?.kort ?? 0),
      verlopen: Number(c?.verlopen ?? 0),
      dezeMaand: Number(c?.deze_maand ?? 0),
    },
    bijnaVerlopen: verloopt.map((r) => ({
      id: r.id,
      product: r.product,
      locatie: r.locatie,
      conservering: r.conservering ?? "Vers",
      hoeveelheid: Number(r.quantity),
      eenheid: r.eenheid ?? "",
      houdbaarTot: String(r.houdbaar_tot).slice(0, 10),
    })),
    totalen: totalen.map((r) => ({
      sleutel: `${r.product_id}-${r.conservering ?? "vers"}`,
      product: r.product,
      conservering: r.conservering ?? "Vers",
      eenheid: r.eenheid ?? "",
      totaal: Number(r.totaal),
      locaties: Number(r.locaties),
    })),
  };
}

export type NieuweOogst = {
  productId: number;
  locatieId: number;
  conserveringId: number | null;
  hoeveelheid: number;
  datum: string;
  houdbaarTot: string | null;
  notitie: string | null;
};

export async function bewaarOogst(
  invoer: NieuweOogst,
  gebruikersnaam: string,
): Promise<{ id: number }> {
  const rijen = await db()<Array<{ id: number }>>`
    INSERT INTO harvest_entries
      (product_id, location_id, conserveringsmethode_id, quantity, date,
       entered_by, note, houdbaar_tot)
    VALUES
      (${invoer.productId}, ${invoer.locatieId}, ${invoer.conserveringId},
       ${invoer.hoeveelheid}, ${invoer.datum}, ${gebruikersnaam},
       ${invoer.notitie}, ${invoer.houdbaarTot})
    RETURNING id
  `;
  return { id: rijen[0]?.id ?? 0 };
}

// ── Voorraadoverzicht ──────────────────────────────────────────────────────

export type Partij = {
  id: number;
  productId: number;
  product: string;
  locatieId: number;
  locatie: string;
  conservering: string;
  hoeveelheid: number;
  eenheid: string;
  datum: string;
  houdbaarTot: string | null;
  notitie: string | null;
};

export type VoorraadData = {
  peildatum: string;
  partijen: Partij[];
  producten: Array<{ id: number; naam: string }>;
  locaties: Array<{ id: number; naam: string }>;
};

async function haalOpenPartijen(): Promise<Partij[]> {
  const rijen = await db()<
    Array<{
      id: number;
      product_id: number;
      product: string;
      location_id: number;
      locatie: string;
      conservering: string | null;
      quantity: number;
      eenheid: string | null;
      date: string;
      houdbaar_tot: string | null;
      note: string | null;
    }>
  >`
    SELECT h.id, h.product_id, p.name AS product,
           h.location_id, l.name AS locatie,
           c.naam AS conservering,
           h.quantity, COALESCE(e.naam, p.unit) AS eenheid,
           h.date, h.houdbaar_tot, h.note
    FROM harvest_entries h
    JOIN products  p ON p.id = h.product_id
    JOIN locations l ON l.id = h.location_id
    LEFT JOIN conserveringsmethoden c ON c.id = h.conserveringsmethode_id
    LEFT JOIN eenheden e ON e.id = p.eenheid_id
    WHERE NOT h.uitgegeven AND h.quantity > 0
    ORDER BY h.houdbaar_tot NULLS LAST, p.name
  `;

  return rijen.map((r) => ({
    id: r.id,
    productId: r.product_id,
    product: r.product,
    locatieId: r.location_id,
    locatie: r.locatie,
    conservering: r.conservering ?? "Vers",
    hoeveelheid: Number(r.quantity),
    eenheid: r.eenheid ?? "",
    datum: String(r.date).slice(0, 10),
    houdbaarTot: r.houdbaar_tot ? String(r.houdbaar_tot).slice(0, 10) : null,
    notitie: r.note,
  }));
}

export async function haalVoorraad(): Promise<VoorraadData> {
  const sql = db();
  const [partijen, producten, locaties] = await Promise.all([
    haalOpenPartijen(),
    sql<Array<{ id: number; name: string }>>`
      SELECT id, name FROM products WHERE active ORDER BY name
    `,
    sql<Array<{ id: number; name: string }>>`
      SELECT id, name FROM locations WHERE active ORDER BY name
    `,
  ]);

  return {
    peildatum: vandaag(),
    partijen,
    producten: producten.map((p) => ({ id: p.id, naam: p.name })),
    locaties: locaties.map((l) => ({ id: l.id, naam: l.name })),
  };
}

// ── Uitgifte ───────────────────────────────────────────────────────────────

export type UitgifteRegel = {
  id: number;
  product: string;
  locatie: string;
  hoeveelheid: number;
  eenheid: string;
  ontvanger: string;
  datum: string;
  door: string;
  notitie: string | null;
};

export type UitgifteData = {
  peildatum: string;
  partijen: Partij[];
  ontvangers: Array<{ id: number; naam: string }>;
  historie: UitgifteRegel[];
};

export async function haalUitgifteData(): Promise<UitgifteData> {
  const sql = db();
  const [partijen, ontvangers, historie] = await Promise.all([
    haalOpenPartijen(),
    sql<Array<{ id: number; naam: string }>>`
      SELECT id, naam FROM ontvangers WHERE actief ORDER BY naam
    `,
    sql<
      Array<{
        id: number;
        product: string;
        locatie: string;
        quantity: number;
        eenheid: string | null;
        ontvanger: string;
        date: string;
        entered_by: string;
        note: string | null;
      }>
    >`
      SELECT u.id, p.name AS product, l.name AS locatie, u.quantity,
             COALESCE(e.naam, p.unit) AS eenheid,
             u.ontvanger, u.date, u.entered_by, u.note
      FROM uitgiftes u
      JOIN products  p ON p.id = u.product_id
      JOIN locations l ON l.id = u.location_id
      LEFT JOIN eenheden e ON e.id = p.eenheid_id
      ORDER BY u.date DESC, u.id DESC
      LIMIT 50
    `,
  ]);

  return {
    peildatum: vandaag(),
    partijen,
    ontvangers,
    historie: historie.map((r) => ({
      id: r.id,
      product: r.product,
      locatie: r.locatie,
      hoeveelheid: Number(r.quantity),
      eenheid: r.eenheid ?? "",
      ontvanger: r.ontvanger,
      datum: String(r.date).slice(0, 10),
      door: r.entered_by,
      notitie: r.note,
    })),
  };
}

export type NieuweUitgifte = {
  partijId: number;
  hoeveelheid: number;
  ontvanger: string;
  datum: string;
  notitie: string | null;
};

export async function bewaarUitgifte(
  invoer: NieuweUitgifte,
  gebruikersnaam: string,
): Promise<{ id: number; restant: number }> {
  const sql = db();

  const partijen = await sql<
    Array<{
      id: number;
      product_id: number;
      location_id: number;
      quantity: number;
      uitgegeven: boolean;
    }>
  >`
    SELECT id, product_id, location_id, quantity, uitgegeven
    FROM harvest_entries WHERE id = ${invoer.partijId}
  `;
  const partij = partijen[0];
  if (!partij || partij.uitgegeven) {
    throw new Error("Deze partij is niet meer beschikbaar.");
  }

  const beschikbaar = Number(partij.quantity);
  if (invoer.hoeveelheid > beschikbaar + 1e-9) {
    throw new Error(`Er is nog maar ${beschikbaar} beschikbaar in deze partij.`);
  }

  const restant = Math.max(0, Number((beschikbaar - invoer.hoeveelheid).toFixed(6)));

  const rijen = await sql<Array<{ id: number }>>`
    INSERT INTO uitgiftes
      (harvest_entry_id, product_id, location_id, quantity, ontvanger, date, entered_by, note)
    VALUES
      (${partij.id}, ${partij.product_id}, ${partij.location_id},
       ${invoer.hoeveelheid}, ${invoer.ontvanger}, ${invoer.datum},
       ${gebruikersnaam}, ${invoer.notitie})
    RETURNING id
  `;

  if (restant <= 0) {
    await sql`
      UPDATE harvest_entries
      SET quantity = 0, uitgegeven = TRUE, uitgegeven_op = now(),
          uitgegeven_aan = ${invoer.ontvanger}
      WHERE id = ${partij.id}
    `;
  } else {
    await sql`
      UPDATE harvest_entries SET quantity = ${restant} WHERE id = ${partij.id}
    `;
  }

  return { id: rijen[0]?.id ?? 0, restant };
}
