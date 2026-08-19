import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

export const haalBoodschappenData = createServerFn({ method: "GET" }).handler(
  async () => {
    const { vereisGebruiker } = await import("./auth.server");
    const { haalBoodschappen } = await import("./winkel.server");
    await vereisGebruiker();
    return haalBoodschappen();
  },
);

export const haalGeopendData = createServerFn({ method: "GET" }).handler(
  async () => {
    const { vereisGebruiker } = await import("./auth.server");
    const { haalGeopend } = await import("./winkel.server");
    await vereisGebruiker();
    return haalGeopend();
  },
);

export const voegWinkelItemToe = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        naam: z.string().min(1).max(200),
        merk: z.string().max(200).nullable(),
        categorie: z.string().max(100).nullable(),
        eenheid: z.string().min(1).max(50),
        voorraad: z.number().int().min(0).max(100000),
        minimumVoorraad: z.number().int().min(0).max(100000).nullable(),
        houdbaarTot: z
          .string()
          .regex(/^\d{4}-\d{2}-\d{2}$/)
          .nullable(),
        barcode: z.string().max(64).nullable(),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { bewaarWinkelItem } = await import("./winkel.server");
    const gebruiker = await vereisGebruiker();
    return bewaarWinkelItem(data, gebruiker.username);
  });

export const pasVoorraadAan = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        itemId: z.number().int().positive(),
        verschil: z.number().int().min(-1000).max(1000),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { wijzigVoorraad } = await import("./winkel.server");
    await vereisGebruiker();
    return wijzigVoorraad(data.itemId, data.verschil);
  });

export const openWinkelItem = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z.object({ itemId: z.number().int().positive() }).parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { openItem } = await import("./winkel.server");
    const gebruiker = await vereisGebruiker();
    return openItem(data.itemId, gebruiker.username);
  });

export const zetNiveauVanItem = createServerFn({ method: "POST" })
  .inputValidator((invoer: unknown) =>
    z
      .object({
        itemId: z.number().int().positive(),
        niveau: z.enum(["vol", "driekwart", "half", "kwart", "bijna leeg", "leeg"]),
      })
      .parse(invoer),
  )
  .handler(async ({ data }) => {
    const { vereisGebruiker } = await import("./auth.server");
    const { zetNiveau } = await import("./winkel.server");
    const gebruiker = await vereisGebruiker();
    return zetNiveau(data.itemId, data.niveau, gebruiker.username);
  });
