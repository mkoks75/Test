import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

export const haalDashboardData = createServerFn({ method: "GET" }).handler(
  async () => {
    const { vereisGebruiker } = await import("./auth.server");
    const { haalDashboard } = await import("./voorraad.server");
    await vereisGebruiker();
    return haalDashboard();
  },
);

export const haalStamdataVoorInvoer = createServerFn({ method: "GET" }).handler(
  async () => {
    const { vereisGebruiker } = await import("./auth.server");
    const { haalStamdata } = await import("./voorraad.server");
    await vereisGebruiker();
    return haalStamdata();
  },
);

export const registreerOogst = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        productId: z.number().int().positive(),
        locatieId: z.number().int().positive(),
        conserveringId: z.number().int().positive().nullable(),
        hoeveelheid: z.number().positive().max(1_000_000),
        datum: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        houdbaarTot: z
          .string()
          .regex(/^\d{4}-\d{2}-\d{2}$/)
          .nullable(),
        notitie: z.string().max(1000).nullable(),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { bewaarOogst } = await import("./voorraad.server");
    const gebruiker = await vereisGebruiker();
    return bewaarOogst(data, gebruiker.username);
  });

export const haalVoorraadData = createServerFn({ method: "GET" }).handler(
  async () => {
    const { vereisGebruiker } = await import("./auth.server");
    const { haalVoorraad } = await import("./voorraad.server");
    await vereisGebruiker();
    return haalVoorraad();
  },
);

export const haalUitgifte = createServerFn({ method: "GET" }).handler(async () => {
  const { vereisGebruiker } = await import("./auth.server");
  const { haalUitgifteData } = await import("./voorraad.server");
  await vereisGebruiker();
  return haalUitgifteData();
});

export const registreerUitgifte = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        partijId: z.number().int().positive(),
        hoeveelheid: z.number().positive().max(1_000_000),
        ontvanger: z.string().min(1).max(200),
        datum: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        notitie: z.string().max(1000).nullable(),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { bewaarUitgifte } = await import("./voorraad.server");
    const gebruiker = await vereisGebruiker();
    return bewaarUitgifte(data, gebruiker.username);
  });

export const haalPartij = createServerFn({ method: "GET" })
  .inputValidator((invoer: unknown) =>
    z.object({ id: z.number().int().positive() }).parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { haalPartijDetail } = await import("./voorraad.server");
    await vereisGebruiker();
    return haalPartijDetail(data.id);
  });
