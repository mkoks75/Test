/**
 * Wachtwoord-herstel. Server-only.
 *
 * Tokens zijn eenmalig bruikbaar en verlopen na een uur. De link wordt
 * verstuurd via SMTP zodra dat is ingericht; zolang dat niet zo is, komt de
 * link in de serverlog te staan zodat een beheerder hem kan doorgeven.
 */

import { db } from "./db.server";
import { hashWachtwoord } from "./auth.server";

const GELDIG_MINUTEN = 60;

export async function maakHerstelToken(userId: number): Promise<string> {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const token = Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

  const verlooptOp = new Date(Date.now() + GELDIG_MINUTEN * 60_000);

  // Openstaande tokens van deze gebruiker vervallen.
  await db()`
    UPDATE password_reset_tokens SET used = TRUE
    WHERE user_id = ${userId} AND used = FALSE
  `;
  await db()`
    INSERT INTO password_reset_tokens (user_id, token, expires_at, used)
    VALUES (${userId}, ${token}, ${verlooptOp}, FALSE)
  `;

  return token;
}

export function herstelUrl(token: string): string {
  const basis = (process.env["APP_URL"] ?? "").replace(/\/$/, "");
  return `${basis}/wachtwoord-herstellen?token=${token}`;
}

export async function verstuurHerstelMail(
  email: string,
  token: string,
): Promise<void> {
  const url = herstelUrl(token);

  // SMTP-verzending wordt aangezet zodra de app op de eigen server draait.
  // Tot die tijd is de log de bezorgmethode; het adres loggen we niet mee.
  console.info(
    `[wachtwoord-herstel] link aangemaakt, geldig ${GELDIG_MINUTEN} minuten: ${url}`,
  );
  void email;
}

export async function gebruikHerstelToken(
  token: string,
  nieuwWachtwoord: string,
): Promise<{ ok: boolean; melding?: string }> {
  const rijen = await db()<
    Array<{ id: number; user_id: number; expires_at: Date; used: boolean }>
  >`
    SELECT id, user_id, expires_at, used
    FROM password_reset_tokens
    WHERE token = ${token}
  `;

  const rij = rijen[0];
  if (!rij || rij.used || new Date(rij.expires_at).getTime() < Date.now()) {
    return { ok: false, melding: "Deze link is verlopen of al gebruikt." };
  }

  const hash = await hashWachtwoord(nieuwWachtwoord);
  await db().begin(async (sql) => {
    await sql`UPDATE users SET hashed_password = ${hash} WHERE id = ${rij.user_id}`;
    await sql`UPDATE password_reset_tokens SET used = TRUE WHERE id = ${rij.id}`;
  });

  return { ok: true };
}
