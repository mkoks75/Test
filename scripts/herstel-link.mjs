#!/usr/bin/env node
/**
 * Maak direct een herstel-link voor een bestaande gebruiker.
 *
 *   node scripts/herstel-link.mjs <gebruikersnaam-of-email>
 *
 * Handig als je niet meer kunt inloggen en geen mail wilt afwachten.
 */

import postgres from "postgres";

const [, , wie] = process.argv;
if (!wie) {
  console.error("Gebruik: node scripts/herstel-link.mjs <gebruikersnaam-of-email>");
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

const sql = postgres(url, { max: 1 });

try {
  const [gebruiker] = await sql`
    SELECT id, username FROM users
    WHERE lower(username) = lower(${wie}) OR lower(email) = lower(${wie})
    LIMIT 1
  `;

  if (!gebruiker) {
    console.error(`Geen gebruiker gevonden voor "${wie}".`);
    process.exit(1);
  }

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
  console.log(`Herstel-link voor ${gebruiker.username} (7 dagen geldig):`);
  console.log(`${basis}/wachtwoord-herstellen?token=${token}`);
} finally {
  await sql.end();
}
