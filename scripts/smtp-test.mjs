/**
 * SMTP-diagnose. Draai in de app-container:
 *
 *   docker-compose exec app node scripts/smtp-test.mjs jouw@adres.nl
 *
 * Toont welke SMTP-variabelen aanwezig zijn (nooit de waarden) en probeert
 * daadwerkelijk een testmail te versturen, met de volledige foutmelding.
 */

import nodemailer from "nodemailer";

const naar = process.argv[2];

const host = process.env.SMTP_HOST;
const port = Number(process.env.SMTP_PORT ?? 587);
const user = process.env.SMTP_USER;
const pass = process.env.SMTP_PASSWORD ?? process.env.SMTP_PASS;
const from = process.env.SMTP_FROM ?? (user ? `Voorraad <${user}>` : undefined);

console.log("SMTP_HOST     :", host ? "aanwezig" : "ONTBREEKT");
console.log("SMTP_PORT     :", port);
console.log("SMTP_USER     :", user ? "aanwezig" : "ONTBREEKT");
console.log("SMTP_PASSWORD :", pass ? "aanwezig" : "ONTBREEKT");
console.log("SMTP_FROM     :", from ? "aanwezig" : "ONTBREEKT");
console.log("APP_URL       :", process.env.APP_URL || "ONTBREEKT");

if (!host || !from) {
  console.error("\nZonder SMTP_HOST en een afzender kan er geen mail uit.");
  process.exit(1);
}
if (!naar) {
  console.error("\nGeef een ontvanger mee: node scripts/smtp-test.mjs jij@adres.nl");
  process.exit(1);
}

const transport = nodemailer.createTransport({
  host,
  port,
  secure: port === 465,
  ...(user && pass ? { auth: { user, pass } } : {}),
});

try {
  await transport.verify();
  console.log("\nVerbinding met de mailserver: OK");
  const info = await transport.sendMail({
    from,
    to: naar,
    subject: "SMTP-test — MountainSense Farm voorraad",
    text: "Deze testmail bevestigt dat het versturen werkt.",
  });
  console.log("Verstuurd:", info.messageId, info.response ?? "");
} catch (fout) {
  console.error("\nVersturen mislukt:", fout);
  process.exit(1);
}
