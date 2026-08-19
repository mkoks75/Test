/**
 * Wachtwoorden en sessies. Server-only.
 *
 * Wachtwoorden worden gehasht met PBKDF2-SHA256 via WebCrypto, zodat het
 * zowel in de Lovable-preview als op de Node-server op Hetzner werkt.
 * De oude bcrypt-hashes uit de Python-applicatie worden bewust niet
 * overgenomen: iedereen stelt eenmalig een nieuw wachtwoord in.
 */

import { useSession } from "@tanstack/react-start/server";

import { db } from "./db.server";

const ITERATIES = 210_000;
const ZOUT_BYTES = 16;
const SLEUTEL_BITS = 256;

export type Gebruiker = {
  id: number;
  username: string;
  email: string | null;
  isAdmin: boolean;
};

type SessieData = { userId?: number };

function sessieConfig() {
  const password = process.env["SESSION_SECRET"];
  if (!password || password.length < 32) {
    throw new Error(
      "SESSION_SECRET ontbreekt of is te kort (minimaal 32 tekens).",
    );
  }
  return {
    password,
    name: "voorraad-sessie",
    maxAge: 60 * 60 * 24 * 30,
    cookie: {
      httpOnly: true,
      sameSite: "lax" as const,
      secure: process.env["NODE_ENV"] === "production",
      path: "/",
    },
  };
}

// ── Wachtwoorden ───────────────────────────────────────────────────────────

function naarHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function vanHex(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

async function afleiden(
  wachtwoord: string,
  zout: Uint8Array,
  iteraties: number,
): Promise<string> {
  const sleutel = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(wachtwoord),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: zout as BufferSource, iterations: iteraties, hash: "SHA-256" },
    sleutel,
    SLEUTEL_BITS,
  );
  return naarHex(bits);
}

/** Formaat: pbkdf2$<iteraties>$<zout-hex>$<hash-hex> */
export async function hashWachtwoord(wachtwoord: string): Promise<string> {
  const zout = crypto.getRandomValues(new Uint8Array(ZOUT_BYTES));
  const hash = await afleiden(wachtwoord, zout, ITERATIES);
  return `pbkdf2$${ITERATIES}$${naarHex(zout.buffer)}$${hash}`;
}

export async function controleerWachtwoord(
  wachtwoord: string,
  opgeslagen: string,
): Promise<boolean> {
  const delen = opgeslagen.split("$");
  if (delen.length !== 4 || delen[0] !== "pbkdf2") return false;

  const iteraties = Number(delen[1]);
  const zout = vanHex(delen[2] ?? "");
  const verwacht = delen[3] ?? "";
  if (!Number.isFinite(iteraties) || iteraties <= 0) return false;

  const berekend = await afleiden(wachtwoord, zout, iteraties);
  return tijdveiligGelijk(berekend, verwacht);
}

function tijdveiligGelijk(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let verschil = 0;
  for (let i = 0; i < a.length; i += 1) {
    verschil |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return verschil === 0;
}

// ── Sessie ─────────────────────────────────────────────────────────────────

export async function zetSessie(userId: number): Promise<void> {
  const sessie = await useSession<SessieData>(sessieConfig());
  await sessie.update({ userId });
}

export async function wisSessie(): Promise<void> {
  const sessie = await useSession<SessieData>(sessieConfig());
  await sessie.clear();
}

/** De ingelogde gebruiker, of null. Leest de sessiecookie van het verzoek. */
export async function huidigeGebruiker(): Promise<Gebruiker | null> {
  let userId: number | undefined;
  try {
    const sessie = await useSession<SessieData>(sessieConfig());
    userId = sessie.data.userId;
  } catch {
    return null;
  }
  if (!userId) return null;

  const rijen = await db()<
    Array<{ id: number; username: string; email: string | null; is_admin: boolean }>
  >`
    SELECT id, username, email, is_admin
    FROM users
    WHERE id = ${userId}
  `;

  const rij = rijen[0];
  if (!rij) return null;
  return {
    id: rij.id,
    username: rij.username,
    email: rij.email,
    isAdmin: rij.is_admin,
  };
}

/** Gooit als er niemand is ingelogd. Gebruik in elke beschermde server function. */
export async function vereisGebruiker(): Promise<Gebruiker> {
  const gebruiker = await huidigeGebruiker();
  if (!gebruiker) throw new Error("Niet ingelogd");
  return gebruiker;
}

export async function vereisAdmin(): Promise<Gebruiker> {
  const gebruiker = await vereisGebruiker();
  if (!gebruiker.isAdmin) throw new Error("Geen beheerrechten");
  return gebruiker;
}
