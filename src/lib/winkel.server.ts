/**
 * Winkelvoorraad ("Boodschappen") en geopende producten. Server-only.
 *
 * shop_items.status kent drie waarden: 'voorraad' (ongeopend in de kast),
 * 'geopend' (in gebruik) en 'op' (verbruikt). Niveauwijzigingen van geopende
 * producten worden gelogd in niveau_logs.
 */

import { db } from "./db.server";
import { vandaag } from "./datum";

export type WinkelItem = {
  id: number;
  naam: string;
  merk: string | null;
  categorie: string | null;
  eenheid: string;
  hoeveelheidPerEenheid: number;
  voorraad: number;
  minimumVoorraad: number | null;
  houdbaarTot: string | null;
  eigenaar: string;
  barcode: string | null;
  status: string;
  niveauStap: string | null;
  deelbaar: boolean;
};

export type BoodschappenData = {
  peildatum: string;
  items: WinkelItem[];
  categorieen: string[];
};

export type GeopendData = {
  peildatum: string;
  items: WinkelItem[];
  logs: Array<{
    id: number;
    item: string;
    niveauStap: string;
    door: string;
    moment: string;
  }>;
};

type Rij = {
  id: number;
  name: string;
  brand: string | null;
  categorie: string | null;
  unit: string | null;
  quantity_per_unit: number | null;
  stock: number | null;
  minimum_stock: number | null;
  houdbaar_tot: string | null;
  owner: string;
  barcode: string | null;
  status: string | null;
  niveau_stap: string | null;
  is_deelbaar: boolean | null;
};

function naarItem(r: Rij): WinkelItem {
  return {
    id: r.id,
    naam: r.name,
    merk: r.brand,
    categorie: r.categorie,
    eenheid: r.unit ?? "stuks",
    hoeveelheidPerEenheid: Number(r.quantity_per_unit ?? 1),
    voorraad: Number(r.stock ?? 0),
    minimumVoorraad: r.minimum_stock === null ? null : Number(r.minimum_stock),
    houdbaarTot: r.houdbaar_tot ? String(r.houdbaar_tot).slice(0, 10) : null,
    eigenaar: r.owner,
    barcode: r.barcode,
    status: r.status ?? "voorraad",
    niveauStap: r.niveau_stap,
    deelbaar: Boolean(r.is_deelbaar),
  };
}

const kolommen = `id, name, brand, categorie, unit, quantity_per_unit, stock,
  minimum_stock, houdbaar_tot, owner, barcode, status, niveau_stap, is_deelbaar`;

export async function haalBoodschappen(): Promise<BoodschappenData> {
  const sql = db();
  const rijen = await sql<Rij[]>`
    SELECT ${sql.unsafe(kolommen)}
    FROM shop_items
    WHERE COALESCE(status, 'voorraad') = 'voorraad'
    ORDER BY (houdbaar_tot IS NULL), houdbaar_tot, name
  `;
  const items = rijen.map(naarItem);
  const categorieen = [
    ...new Set(items.map((i) => i.categorie).filter((c): c is string => Boolean(c))),
  ].sort((a, b) => a.localeCompare(b, "nl"));

  return { peildatum: vandaag(), items, categorieen };
}

export async function haalGeopend(): Promise<GeopendData> {
  const sql = db();
  const [rijen, logs] = await Promise.all([
    sql<Rij[]>`
      SELECT ${sql.unsafe(kolommen)}
      FROM shop_items
      WHERE status = 'geopend'
      ORDER BY (houdbaar_tot IS NULL), houdbaar_tot, name
    `,
    sql<
      Array<{
        id: number;
        name: string;
        niveau_stap: string;
        gewijzigd_door: string;
        timestamp: string;
      }>
    >`
      SELECT n.id, s.name, n.niveau_stap, n.gewijzigd_door, n.timestamp
      FROM niveau_logs n
      JOIN shop_items s ON s.id = n.shop_item_id
      ORDER BY n.timestamp DESC, n.id DESC
      LIMIT 25
    `,
  ]);

  return {
    peildatum: vandaag(),
    items: rijen.map(naarItem),
    logs: logs.map((l) => ({
      id: l.id,
      item: l.name,
      niveauStap: l.niveau_stap,
      door: l.gewijzigd_door,
      moment: new Date(l.timestamp).toISOString(),
    })),
  };
}

export type NieuwWinkelItem = {
  naam: string;
  merk: string | null;
  categorie: string | null;
  eenheid: string;
  voorraad: number;
  minimumVoorraad: number | null;
  houdbaarTot: string | null;
  barcode: string | null;
};

export async function bewaarWinkelItem(
  invoer: NieuwWinkelItem,
  gebruikersnaam: string,
): Promise<{ id: number }> {
  const sql = db();
  const rijen = await sql<Array<{ id: number }>>`
    INSERT INTO shop_items
      (name, brand, categorie, unit, stock, minimum_stock, houdbaar_tot,
       barcode, owner, entered_by, status, date_added)
    VALUES
      (${invoer.naam}, ${invoer.merk}, ${invoer.categorie}, ${invoer.eenheid},
       ${invoer.voorraad}, ${invoer.minimumVoorraad}, ${invoer.houdbaarTot},
       ${invoer.barcode}, ${gebruikersnaam}, ${gebruikersnaam}, 'voorraad',
       CURRENT_DATE)
    RETURNING id
  `;
  return { id: rijen[0]?.id ?? 0 };
}

export async function wijzigVoorraad(
  itemId: number,
  verschil: number,
): Promise<{ voorraad: number }> {
  const sql = db();
  const rijen = await sql<Array<{ stock: number }>>`
    UPDATE shop_items
    SET stock = GREATEST(0, COALESCE(stock, 0) + ${verschil})
    WHERE id = ${itemId}
    RETURNING stock
  `;
  if (!rijen[0]) throw new Error("Product niet gevonden.");
  return { voorraad: Number(rijen[0].stock) };
}

export async function openItem(
  itemId: number,
  gebruikersnaam: string,
): Promise<{ ok: true }> {
  const sql = db();
  const rijen = await sql<Array<{ stock: number }>>`
    SELECT COALESCE(stock, 0) AS stock FROM shop_items WHERE id = ${itemId}
  `;
  if (!rijen[0]) throw new Error("Product niet gevonden.");

  await sql`
    UPDATE shop_items
    SET status = 'geopend', niveau_stap = 'vol',
        stock = GREATEST(0, COALESCE(stock, 0) - 1)
    WHERE id = ${itemId}
  `;
  await sql`
    INSERT INTO niveau_logs (shop_item_id, niveau_stap, gewijzigd_door)
    VALUES (${itemId}, 'vol', ${gebruikersnaam})
  `;
  return { ok: true };
}

export const niveaustappen = ["vol", "driekwart", "half", "kwart", "bijna leeg", "leeg"] as const;

export async function zetNiveau(
  itemId: number,
  niveau: string,
  gebruikersnaam: string,
): Promise<{ ok: true; status: string }> {
  const sql = db();
  const status = niveau === "leeg" ? "op" : "geopend";

  const rijen = await sql<Array<{ id: number }>>`
    UPDATE shop_items
    SET niveau_stap = ${niveau}, status = ${status}
    WHERE id = ${itemId}
    RETURNING id
  `;
  if (!rijen[0]) throw new Error("Product niet gevonden.");

  await sql`
    INSERT INTO niveau_logs (shop_item_id, niveau_stap, gewijzigd_door)
    VALUES (${itemId}, ${niveau}, ${gebruikersnaam})
  `;
  return { ok: true, status };
}
