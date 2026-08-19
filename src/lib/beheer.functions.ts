import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

const soort = z.enum(["product", "locatie", "eenheid", "conservering", "ontvanger"]);

export const haalBeheer = createServerFn({ method: "GET" }).handler(async () => {
  const { vereisAdmin } = await import("./auth.server");
  const { haalBeheerData } = await import("./beheer.server");
  await vereisAdmin();
  return haalBeheerData();
});

export const voegStamdataItemToe = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        soort,
        naam: z.string().min(1).max(200),
        eenheidId: z.number().int().positive().nullable().default(null),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisAdmin } = await import("./auth.server");
    const { voegStamdataToe } = await import("./beheer.server");
    await vereisAdmin();
    return voegStamdataToe(data.soort, data.naam, data.eenheidId);
  });

export const wijzigStamdataItem = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        soort,
        id: z.number().int().positive(),
        naam: z.string().min(1).max(200),
        actief: z.boolean(),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisAdmin } = await import("./auth.server");
    const { wijzigStamdata } = await import("./beheer.server");
    await vereisAdmin();
    return wijzigStamdata(data.soort, data.id, data.naam, data.actief);
  });

export const bewaarHoudbaarheidsregel = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        productId: z.number().int().positive(),
        conserveringId: z.number().int().positive().nullable(),
        maanden: z.number().int().min(1).max(600),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisAdmin } = await import("./auth.server");
    const { bewaarHoudbaarheid } = await import("./beheer.server");
    await vereisAdmin();
    return bewaarHoudbaarheid(data);
  });
