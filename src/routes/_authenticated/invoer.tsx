import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { formatteerDatum, plusMaanden, vandaag } from "@/lib/datum";
import {
  haalStamdataVoorInvoer,
  registreerOogst,
} from "@/lib/voorraad.functions";

export const Route = createFileRoute("/_authenticated/invoer")({
  loader: () => haalStamdataVoorInvoer(),
  head: () => ({
    meta: [
      { title: "Oogst registreren — MountainSense Farm voorraad" },
      {
        name: "description",
        content:
          "Registreer een nieuwe oogstpartij met product, conservering, locatie en automatisch berekende houdbaarheidsdatum.",
      },
      { property: "og:title", content: "Oogst registreren — MountainSense Farm" },
      {
        property: "og:description",
        content:
          "Nieuwe oogstpartij vastleggen met automatische berekening van de houdbaarheidsdatum.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: InvoerPagina,
});

const veldClasses =
  "w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/25";

const labelClasses =
  "mb-1.5 block text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground";

function InvoerPagina() {
  const stamdata = Route.useLoaderData();
  const opslaan = useServerFn(registreerOogst);

  const [productId, setProductId] = useState(stamdata.producten[0]?.id ?? 0);
  const [conserveringId, setConserveringId] = useState<number | null>(
    stamdata.conserveringsmethoden[0]?.id ?? null,
  );
  const [locatieId, setLocatieId] = useState(stamdata.locaties[0]?.id ?? 0);
  const [hoeveelheid, setHoeveelheid] = useState("");
  const [datum, setDatum] = useState(() => vandaag());
  const [handmatigHoudbaar, setHandmatigHoudbaar] = useState("");
  const [notitie, setNotitie] = useState("");
  const [bevestiging, setBevestiging] = useState<string | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);

  const product = stamdata.producten.find((p) => p.id === productId);

  const termijn = useMemo(() => {
    const exact = stamdata.bewaartermijnen.find(
      (t) => t.productId === productId && t.conserveringId === conserveringId,
    );
    if (exact) return exact.maanden;
    const algemeen = stamdata.bewaartermijnen.find(
      (t) => t.productId === productId && t.conserveringId === null,
    );
    return algemeen?.maanden ?? null;
  }, [stamdata.bewaartermijnen, productId, conserveringId]);

  const berekendHoudbaar = useMemo(
    () => (termijn === null ? null : plusMaanden(datum, termijn)),
    [termijn, datum],
  );
  const effectiefHoudbaar = handmatigHoudbaar || berekendHoudbaar;

  const geenStamdata =
    stamdata.producten.length === 0 || stamdata.locaties.length === 0;

  async function verstuur(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBezig(true);
    setFout(null);
    setBevestiging(null);
    try {
      await opslaan({
        data: {
          productId,
          locatieId,
          conserveringId,
          hoeveelheid: Number(hoeveelheid.replace(",", ".")),
          datum,
          houdbaarTot: effectiefHoudbaar || null,
          notitie: notitie.trim() || null,
        },
      });

      const locatie = stamdata.locaties.find((l) => l.id === locatieId);
      setBevestiging(
        `${product?.naam ?? "Product"} — ${hoeveelheid} ${product?.eenheid ?? ""} op ${
          locatie?.naam ?? "—"
        }${
          effectiefHoudbaar
            ? `, houdbaar tot ${formatteerDatum(effectiefHoudbaar)}`
            : ""
        }.`,
      );
      setHoeveelheid("");
      setNotitie("");
      setHandmatigHoudbaar("");
    } catch {
      setFout("Opslaan is niet gelukt. Probeer het opnieuw.");
    } finally {
      setBezig(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 lg:py-14">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
          Registreren
        </p>
        <h1 className="mt-2 text-3xl tracking-tight text-foreground sm:text-4xl">
          Nieuwe oogstpartij
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          De houdbaarheidsdatum wordt berekend uit het bewaarschema van product
          en conserveringsmethode. Je kunt hem altijd handmatig overschrijven.
        </p>

        {geenStamdata ? (
          <p className="mt-6 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-foreground">
            Er staan nog geen producten of locaties in de database. Voer die
            eerst in of importeer de bestaande gegevens.
          </p>
        ) : null}

        {bevestiging ? (
          <div
            role="status"
            className="mt-6 rounded-lg border border-success/40 bg-success/10 px-4 py-3 text-sm text-foreground"
          >
            <span className="font-semibold text-success">Opgeslagen — </span>
            {bevestiging}
          </div>
        ) : null}

        {fout ? (
          <p
            role="alert"
            className="mt-6 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-foreground"
          >
            {fout}
          </p>
        ) : null}

        <form
          onSubmit={verstuur}
          className="mt-8 rounded-xl border border-border bg-card p-5 shadow-xs sm:p-7"
        >
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label htmlFor="product" className={labelClasses}>
                Product
              </label>
              <select
                id="product"
                className={veldClasses}
                value={productId}
                onChange={(e) => setProductId(Number(e.target.value))}
              >
                {stamdata.producten.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.naam}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="conservering" className={labelClasses}>
                Conservering
              </label>
              <select
                id="conservering"
                className={veldClasses}
                value={conserveringId ?? ""}
                onChange={(e) =>
                  setConserveringId(
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
              >
                <option value="">Vers</option>
                {stamdata.conserveringsmethoden.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.naam}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-xs text-muted-foreground">
                {termijn === null
                  ? "Geen bewaartermijn bekend voor deze combinatie."
                  : `Bewaartermijn: ${termijn} maand${termijn === 1 ? "" : "en"}.`}
              </p>
            </div>

            <div>
              <label htmlFor="locatie" className={labelClasses}>
                Locatie
              </label>
              <select
                id="locatie"
                className={veldClasses}
                value={locatieId}
                onChange={(e) => setLocatieId(Number(e.target.value))}
              >
                {stamdata.locaties.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.naam}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="hoeveelheid" className={labelClasses}>
                Hoeveelheid ({product?.eenheid || "—"})
              </label>
              <input
                id="hoeveelheid"
                className={`${veldClasses} tnum`}
                type="number"
                min="0"
                step="0.1"
                inputMode="decimal"
                placeholder="0,0"
                value={hoeveelheid}
                onChange={(e) => setHoeveelheid(e.target.value)}
                required
              />
            </div>

            <div>
              <label htmlFor="datum" className={labelClasses}>
                Oogstdatum
              </label>
              <input
                id="datum"
                className={`${veldClasses} tnum`}
                type="date"
                value={datum}
                onChange={(e) => setDatum(e.target.value)}
                required
              />
            </div>

            <div className="sm:col-span-2">
              <label htmlFor="houdbaar" className={labelClasses}>
                Houdbaar tot
              </label>
              <input
                id="houdbaar"
                className={`${veldClasses} tnum`}
                type="date"
                value={handmatigHoudbaar || berekendHoudbaar || ""}
                onChange={(e) => setHandmatigHoudbaar(e.target.value)}
              />
              <p className="mt-1.5 text-xs text-muted-foreground">
                {berekendHoudbaar
                  ? `Automatisch berekend op ${formatteerDatum(berekendHoudbaar)}.`
                  : "Vul zelf een datum in, of laat leeg."}
              </p>
            </div>

            <div className="sm:col-span-2">
              <label htmlFor="notitie" className={labelClasses}>
                Notitie
              </label>
              <textarea
                id="notitie"
                rows={3}
                className={veldClasses}
                placeholder="Bijvoorbeeld: laatste snee van het perceel."
                value={notitie}
                onChange={(e) => setNotitie(e.target.value)}
              />
            </div>
          </div>

          <div className="mt-7 flex flex-wrap items-center gap-3 border-t border-border pt-6">
            <button
              type="submit"
              disabled={bezig || geenStamdata}
              className="rounded-md bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {bezig ? "Bezig…" : "Partij registreren"}
            </button>
            <span className="text-sm text-muted-foreground">
              Oogstdatum {formatteerDatum(datum)}
            </span>
          </div>
        </form>
      </div>
    </AppShell>
  );
}
