import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

/** Wie is er ingelogd? Geeft null terug in plaats van te falen. */
export const haalHuidigeGebruiker = createServerFn({ method: "GET" }).handler(
  async () => {
    const { huidigeGebruiker } = await import("./auth.server");
    try {
      return await huidigeGebruiker();
    } catch {
      return null;
    }
  },
);

export const inloggen = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        gebruikersnaam: z.string().min(1).max(120),
        wachtwoord: z.string().min(1).max(512),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { controleerWachtwoord, zetSessie } = await import("./auth.server");
    const { db } = await import("./db.server");

    const rijen = await db()<
      Array<{ id: number; hashed_password: string }>
    >`
      SELECT id, hashed_password
      FROM users
      WHERE lower(username) = lower(${data.gebruikersnaam})
    `;

    const rij = rijen[0];
    // Ook zonder gevonden gebruiker een hash controleren, zodat de reactietijd
    // niet verraadt of de gebruikersnaam bestaat.
    const opgeslagen =
      rij?.hashed_password ?? "pbkdf2$210000$00$00";
    const klopt = await controleerWachtwoord(data.wachtwoord, opgeslagen);

    if (!rij || !klopt) {
      return { ok: false as const, melding: "Onbekende combinatie." };
    }

    await zetSessie(rij.id);
    return { ok: true as const };
  });

export const uitloggen = createServerFn({ method: "POST" }).handler(async () => {
  const { wisSessie } = await import("./auth.server");
  await wisSessie();
  return { ok: true as const };
});

/**
 * Vraag een herstel-link aan. Geeft altijd hetzelfde antwoord, of het adres nu
 * bestaat of niet. De link wordt server-side gelogd en — zodra SMTP is
 * ingericht — gemaild.
 */
export const vraagHerstelLink = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z.object({ email: z.string().email().max(200) }).parse(invoer),
  )
  .handler(async ({ data }) => {
    const { db } = await import("./db.server");
    const { maakHerstelToken, verstuurHerstelMail } = await import(
      "./herstel.server"
    );

    const rijen = await db()<Array<{ id: number; email: string | null }>>`
      SELECT id, email FROM users WHERE lower(email) = lower(${data.email})
    `;

    const rij = rijen[0];
    if (rij?.email) {
      const token = await maakHerstelToken(rij.id);
      await verstuurHerstelMail(rij.email, token);
    }

    return { ok: true as const };
  });

export const herstelWachtwoord = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        token: z.string().min(10).max(200),
        wachtwoord: z.string().min(10).max(512),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { gebruikHerstelToken } = await import("./herstel.server");
    return gebruikHerstelToken(data.token, data.wachtwoord);
  });

export const wijzigEigenWachtwoord = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        huidig: z.string().min(1).max(512),
        nieuw: z.string().min(10).max(512),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker, controleerWachtwoord, hashWachtwoord } =
      await import("./auth.server");
    const { db } = await import("./db.server");

    const gebruiker = await vereisGebruiker();
    const rijen = await db()<Array<{ hashed_password: string }>>`
      SELECT hashed_password FROM users WHERE id = ${gebruiker.id}
    `;

    const opgeslagen = rijen[0]?.hashed_password ?? "";
    if (!(await controleerWachtwoord(data.huidig, opgeslagen))) {
      return { ok: false as const, melding: "Huidig wachtwoord klopt niet." };
    }

    const nieuweHash = await hashWachtwoord(data.nieuw);
    await db()`UPDATE users SET hashed_password = ${nieuweHash} WHERE id = ${gebruiker.id}`;
    return { ok: true as const };
  });
