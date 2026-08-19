/**
 * Wachtwoord-herstel. Server-only.
 *
 * Tokens zijn eenmalig bruikbaar en verlopen na een uur. De link wordt
 * verstuurd via SMTP zodra dat is ingericht; zolang dat niet zo is, komt de
 * link in de serverlog te staan zodat een beheerder hem kan doorgeven.
 */

import { getRequest } from "@tanstack/react-start/server";

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

/** Basis-URL: APP_URL als die staat, anders het adres van het huidige verzoek. */
function basisUrl(): string {
  const uitEnv = (process.env["APP_URL"] ?? "").trim().replace(/\/$/, "");
  if (uitEnv) return uitEnv;

  try {
    return new URL(getRequest().url).origin;
  } catch {
    return "";
  }
}

export function herstelUrl(token: string): string {
  return `${basisUrl()}/wachtwoord-herstellen?token=${token}`;
}

function tekstMail(url: string): string {
  return [
    "Hallo,",
    "",
    "Er is een nieuw wachtwoord aangevraagd voor het voorraadsysteem van MountainSense Farm.",
    `Stel je wachtwoord in via deze link (geldig ${GELDIG_MINUTEN} minuten):`,
    "",
    url,
    "",
    "Heb je dit niet aangevraagd? Dan hoef je niets te doen.",
  ].join("\n");
}

function htmlMail(url: string): string {
  return `<!doctype html><html lang="nl"><body style="margin:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#1f2a24">
  <div style="max-width:520px;margin:0 auto;padding:32px 24px">
    <h1 style="font-size:22px;margin:0 0 12px">Nieuw wachtwoord instellen</h1>
    <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Er is een nieuw wachtwoord aangevraagd voor het voorraadsysteem van MountainSense Farm. De link hieronder is ${GELDIG_MINUTEN} minuten geldig en kan één keer gebruikt worden.</p>
    <p style="margin:0 0 24px"><a href="${url}" style="display:inline-block;background:#2f5d43;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:8px;font-size:15px">Wachtwoord instellen</a></p>
    <p style="font-size:13px;line-height:1.6;color:#5a6b62;margin:0 0 8px">Werkt de knop niet? Kopieer deze link:<br><span style="word-break:break-all">${url}</span></p>
    <p style="font-size:13px;color:#5a6b62;margin:16px 0 0">Heb je dit niet aangevraagd? Dan hoef je niets te doen.</p>
  </div></body></html>`;
}

export async function verstuurHerstelMail(
  email: string,
  token: string,
): Promise<void> {
  const url = herstelUrl(token);

  const host = process.env["SMTP_HOST"];
  const user = process.env["SMTP_USER"];
  const pass = process.env["SMTP_PASSWORD"] ?? process.env["SMTP_PASS"];
  const from =
    process.env["SMTP_FROM"] ?? (user ? `Voorraad <${user}>` : undefined);

  if (!host || !from) {
    // Geen SMTP ingericht: de log is de bezorgmethode. Het adres loggen we niet.
    console.info(
      `[wachtwoord-herstel] geen SMTP geconfigureerd; link geldig ${GELDIG_MINUTEN} minuten: ${url}`,
    );
    return;
  }

  const poort = Number(process.env["SMTP_PORT"] ?? 587);

  try {
    const nodemailer = (await import("nodemailer")).default;
    const transport = nodemailer.createTransport({
      host,
      port: poort,
      secure: poort === 465,
      ...(user && pass ? { auth: { user, pass } } : {}),
    });

    await transport.sendMail({
      from,
      to: email,
      subject: "Nieuw wachtwoord instellen — MountainSense Farm voorraad",
      text: tekstMail(url),
      html: htmlMail(url),
    });
    console.info("[wachtwoord-herstel] mail verstuurd.");
  } catch (fout) {
    console.error("[wachtwoord-herstel] versturen mislukt:", fout);
    console.info(
      `[wachtwoord-herstel] terugvalpad, link geldig ${GELDIG_MINUTEN} minuten: ${url}`,
    );
  }
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
