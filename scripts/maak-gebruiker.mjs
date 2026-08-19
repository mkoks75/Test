#!/usr/bin/env node
/**
 * Maak of herstel een gebruiker vanaf de opdrachtregel.
 *
 *   node scripts/maak-gebruiker.mjs <gebruikersnaam> <e-mail> [--admin]
 *
 * Het script vraagt niet om een wachtwoord: het zet er een willekeurige op en
 * drukt een eenmalige herstel-link af die je aan de gebruiker doorgeeft.
 * Zo staat er nooit een wachtwoord in je shell-historie.
 */

import postgres from "postgres";

const [, , gebruikersnaam, email, ...rest] = process.argv;
const isAdmin = rest.includes("--admin");

if (!gebruikersnaam || !email) {
  console.error(
    "Gebruik: node scripts/maak-gebruiker.mjs <gebruikersnaam> <e-mail> [--admin]",
  );
  process.exit(1);
}

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL ontbreekt.");
  process.exit(1);
}

const hex = (bytes) =>
  Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

async function hashWachtwoord(wachtwoord) {
  const iteraties = 210_000;
  const zout = crypto.getRandomValues(new Uint8Array(16));
  const sleutel = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(wachtwoord),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: zout, iterations: iteraties, hash: "SHA-256" },
    sleutel,
    256,
  );
  return `pbkdf2$${iteraties}$${hex(zout)}$${hex(new Uint8Array(bits))}`;
}

const sql = postgres(url, { max: 1 });

try {
  const hash = await hashWachtwoord(hex(crypto.getRandomValues(new Uint8Array(32))));

  const [gebruiker] = await sql`
    INSERT INTO users (username, email, hashed_password, is_admin)
    VALUES (${gebruikersnaam}, ${email}, ${hash}, ${isAdmin})
    ON CONFLICT (username) DO UPDATE
      SET email = EXCLUDED.email, is_admin = EXCLUDED.is_admin
    RETURNING id
  `;

  const token = hex(crypto.getRandomValues(new Uint8Array(32)));
  await sql`
    UPDATE password_reset_tokens SET used = TRUE
    WHERE user_id = ${gebruiker.id} AND used = FALSE
  `;
  await sql`
    INSERT INTO password_reset_tokens (user_id, token, expires_at, used)
    VALUES (${gebruiker.id}, ${token}, now() + interval '7 days', FALSE)
  `;

  const basis = (process.env.APP_URL ?? "").replace(/\/$/, "");
  console.log(`Gebruiker ${gebruikersnaam} klaar (id ${gebruiker.id}).`);
  console.log(`Herstel-link (7 dagen geldig):`);
  console.log(`${basis}/wachtwoord-herstellen?token=${token}`);
} finally {
  await sql.end();
}
