import { Link, createFileRoute } from "@tanstack/react-router";

import heroHarvest from "@/assets/hero-harvest.jpg";
import { AppShell } from "@/components/AppShell";
import { dagenTot, formatteerDatum, urgentieVan, type Urgentie } from "@/lib/datum";
import { haalDashboardData } from "@/lib/voorraad.functions";

export const Route = createFileRoute("/_authenticated/dashboard")({
  loader: () => haalDashboardData(),
  head: () => ({
    meta: [
      { title: "Voorraaddashboard — MountainSense Farm" },
      {
        name: "description",
        content:
          "Overzicht van de boerderijvoorraad: partijen per locatie, totalen per product en producten die binnenkort verlopen.",
      },
      { property: "og:title", content: "Voorraaddashboard — MountainSense Farm" },
      {
        property: "og:description",
        content:
          "Overzicht van de boerderijvoorraad: partijen per locatie, totalen per product en bijna verlopen oogst.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Dashboard,
});

const urgentieStijl: Record<Urgentie, string> = {
  verlopen: "bg-destructive/12 text-destructive border-destructive/30",
  kritiek: "bg-accent/12 text-accent border-accent/30",
  "let-op": "bg-warning/18 text-warning-foreground border-warning/40",
  ruim: "bg-secondary text-secondary-foreground border-transparent",
};

const urgentieLabel: Record<Urgentie, string> = {
  verlopen: "Verlopen",
  kritiek: "Kritiek",
  "let-op": "Let op",
  ruim: "Ruim",
};

function Dashboard() {
  const { peildatum, cijfers, bijnaVerlopen, totalen } = Route.useLoaderData();

  const tegels = [
    {
      label: "Producten in voorraad",
      waarde: cijfers.productenInVoorraad,
      sub: `${cijfers.partijen} partijen`,
    },
    { label: "Kort houdbaar", waarde: cijfers.kortHoudbaar, sub: "binnen 14 dagen" },
    { label: "Verlopen", waarde: cijfers.verlopen, sub: "actie nodig" },
    { label: "Registraties", waarde: cijfers.dezeMaand, sub: "deze maand" },
  ];

  return (
    <AppShell>
      <section className="relative isolate overflow-hidden border-b border-border">
        <img
          src={heroHarvest}
          alt="Kratten met pas geoogste wortelen, pastinaken en pompoenen in een boerenschuur"
          width={1920}
          height={912}
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-r from-background via-background/85 to-background/25"
        />
        <div className="relative mx-auto w-full max-w-7xl px-4 py-16 sm:px-6 lg:py-24">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-accent">
            Peildatum {formatteerDatum(peildatum)}
          </p>
          <h1 className="mt-3 max-w-2xl text-4xl leading-[1.05] tracking-tight text-foreground sm:text-5xl lg:text-6xl">
            Alles van het land, tot op de dag nauwkeurig bijgehouden.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-muted-foreground">
            Oogst, conservering, locaties en houdbaarheid in één beeld,
            rechtstreeks uit de database op de eigen server.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to="/invoer"
              className="rounded-md bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Oogst registreren
            </Link>
            <a
              href="#bijna-verlopen"
              className="rounded-md border border-border bg-card/80 px-5 py-3 text-sm font-semibold text-foreground backdrop-blur transition-colors hover:bg-card"
            >
              Bekijk wat verloopt
            </a>
          </div>
        </div>
      </section>

      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6 lg:py-16">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {tegels.map((tegel) => (
            <div
              key={tegel.label}
              className="rounded-xl border border-border bg-card p-5 shadow-xs"
            >
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {tegel.label}
              </p>
              <p className="tnum mt-3 font-display text-4xl leading-none text-foreground">
                {tegel.waarde}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">{tegel.sub}</p>
            </div>
          ))}
        </div>

        <section id="bijna-verlopen" className="mt-14 scroll-mt-20">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-2xl tracking-tight text-foreground">
                Bijna verlopen
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Partijen die binnen veertien dagen op hun houdbaarheidsdatum
                komen.
              </p>
            </div>
            <span className="tnum rounded-md bg-surface px-3 py-1.5 text-sm font-medium text-surface-foreground">
              {bijnaVerlopen.length} partijen
            </span>
          </div>

          <div className="mt-5 overflow-hidden rounded-xl border border-border bg-card shadow-xs">
            {bijnaVerlopen.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                Niets dat binnenkort verloopt.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[46rem] text-left text-sm">
                  <thead className="border-b border-border bg-surface text-xs uppercase tracking-[0.1em] text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3 font-semibold">Product</th>
                      <th className="px-4 py-3 font-semibold">Locatie</th>
                      <th className="px-4 py-3 font-semibold">Conservering</th>
                      <th className="px-4 py-3 text-right font-semibold">Aantal</th>
                      <th className="px-4 py-3 font-semibold">Houdbaar tot</th>
                      <th className="px-4 py-3 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bijnaVerlopen.map((regel) => {
                      const urgentie = urgentieVan(regel.houdbaarTot, peildatum);
                      const dagen = dagenTot(regel.houdbaarTot, peildatum);
                      return (
                        <tr
                          key={regel.id}
                          className="border-b border-border/60 last:border-0"
                        >
                          <td className="px-4 py-3 font-medium text-foreground">
                            {regel.product}
                          </td>
                          <td className="px-4 py-3 text-muted-foreground">
                            {regel.locatie}
                          </td>
                          <td className="px-4 py-3 text-muted-foreground">
                            {regel.conservering}
                          </td>
                          <td className="tnum px-4 py-3 text-right text-foreground">
                            {regel.hoeveelheid.toLocaleString("nl-NL")}{" "}
                            <span className="text-muted-foreground">
                              {regel.eenheid}
                            </span>
                          </td>
                          <td className="tnum px-4 py-3 text-muted-foreground">
                            {formatteerDatum(regel.houdbaarTot)}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${urgentieStijl[urgentie]}`}
                            >
                              {urgentieLabel[urgentie]}
                              {dagen >= 0 ? ` · ${dagen}d` : ""}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        <section className="mt-14">
          <h2 className="text-2xl tracking-tight text-foreground">
            Voorraad per product
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Opgeteld over alle locaties, gegroepeerd per conserveringsmethode.
          </p>

          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {totalen.map((regel) => (
              <div
                key={regel.sleutel}
                className="rounded-xl border border-border bg-card p-5 shadow-xs transition-colors hover:border-primary/40"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-lg leading-snug tracking-tight text-foreground">
                    {regel.product}
                  </h3>
                  <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-semibold text-secondary-foreground">
                    {regel.conservering}
                  </span>
                </div>
                <p className="tnum mt-4 font-display text-3xl leading-none text-foreground">
                  {regel.totaal.toLocaleString("nl-NL")}
                  <span className="ml-1.5 font-sans text-sm font-medium text-muted-foreground">
                    {regel.eenheid}
                  </span>
                </p>
                <p className="mt-2 text-sm text-muted-foreground">
                  {regel.locaties} locatie{regel.locaties === 1 ? "" : "s"}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
