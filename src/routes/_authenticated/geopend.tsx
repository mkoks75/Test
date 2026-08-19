import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { History, PackageOpen } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatteerDatum, urgentieVan, type Urgentie } from "@/lib/datum";
import { haalGeopendData, zetNiveauVanItem } from "@/lib/winkel.functions";

export const Route = createFileRoute("/_authenticated/geopend")({
  loader: () => haalGeopendData(),
  head: () => ({
    meta: [
      { title: "Geopend — MountainSense Farm" },
      {
        name: "description",
        content:
          "Alle geopende producten met hun huidige niveau, van vol tot leeg, inclusief wijzigingslog.",
      },
      { property: "og:title", content: "Geopend — MountainSense Farm" },
      {
        property: "og:description",
        content: "Bijhouden hoe vol geopende producten nog zijn.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: GeopendPagina,
});

const niveaus = ["vol", "driekwart", "half", "kwart", "bijna leeg", "leeg"] as const;

const niveauPercentage: Record<(typeof niveaus)[number], number> = {
  vol: 100,
  driekwart: 75,
  half: 50,
  kwart: 25,
  "bijna leeg": 10,
  leeg: 0,
};

const urgentieStijl: Record<Urgentie, string> = {
  verlopen: "border-destructive/30 bg-destructive/12 text-destructive",
  kritiek: "border-accent/30 bg-accent/12 text-accent",
  "let-op": "border-warning/40 bg-warning/18 text-warning-foreground",
  ruim: "border-transparent bg-secondary text-secondary-foreground",
};

function GeopendPagina() {
  const { peildatum, items, logs } = Route.useLoaderData();
  const router = useRouter();
  const zetNiveau = useServerFn(zetNiveauVanItem);
  const [bezig, setBezig] = useState(false);
  const [melding, setMelding] = useState<{ soort: "ok" | "fout"; tekst: string } | null>(
    null,
  );

  async function kies(itemId: number, niveau: (typeof niveaus)[number], naam: string) {
    setBezig(true);
    setMelding(null);
    try {
      await zetNiveau({ data: { itemId, niveau } });
      setMelding({
        soort: "ok",
        tekst:
          niveau === "leeg"
            ? `${naam} is leeg en van de lijst gehaald.`
            : `${naam} staat nu op ${niveau}.`,
      });
      await router.invalidate();
    } catch (fout) {
      setMelding({
        soort: "fout",
        tekst: fout instanceof Error ? fout.message : "Bijwerken is niet gelukt.",
      });
    } finally {
      setBezig(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
        <header className="mb-6">
          <h1 className="font-display text-3xl tracking-tight text-foreground">Geopend</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Producten die in gebruik zijn. Tik het huidige niveau aan om bij te werken.
          </p>
        </header>

        {melding ? (
          <p
            role="status"
            className={`mb-5 rounded-md border px-3 py-2 text-sm ${
              melding.soort === "ok"
                ? "border-primary/25 bg-primary/10 text-foreground"
                : "border-destructive/30 bg-destructive/10 text-destructive"
            }`}
          >
            {melding.tekst}
          </p>
        ) : null}

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-4">
            {items.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-sm text-muted-foreground">
                  <PackageOpen className="mx-auto mb-3 h-8 w-8 opacity-50" aria-hidden />
                  Er staat niets open. Open een product bij Boodschappen.
                </CardContent>
              </Card>
            ) : (
              items.map((item) => {
                const huidig = (item.niveauStap ?? "vol") as (typeof niveaus)[number];
                const percentage = niveauPercentage[huidig] ?? 100;
                return (
                  <Card key={item.id}>
                    <CardContent className="space-y-4 py-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-foreground">
                            {item.naam}
                            {item.merk ? (
                              <span className="text-muted-foreground"> · {item.merk}</span>
                            ) : null}
                          </p>
                          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            {item.categorie ? <span>{item.categorie}</span> : null}
                            {item.houdbaarTot ? (
                              <Badge
                                variant="outline"
                                className={urgentieStijl[urgentieVan(item.houdbaarTot, peildatum)]}
                              >
                                t/m {formatteerDatum(item.houdbaarTot)}
                              </Badge>
                            ) : null}
                          </p>
                        </div>
                        <Badge variant="outline" className="capitalize">
                          {huidig}
                        </Badge>
                      </div>

                      <div
                        className="h-2 w-full overflow-hidden rounded-full bg-secondary"
                        role="img"
                        aria-label={`Niveau ${percentage} procent`}
                      >
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${percentage}%` }}
                        />
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {niveaus.map((n) => (
                          <Button
                            key={n}
                            type="button"
                            size="sm"
                            variant={n === huidig ? "default" : "outline"}
                            disabled={bezig}
                            onClick={() => void kies(item.id, n, item.naam)}
                            className="capitalize"
                          >
                            {n}
                          </Button>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                );
              })
            )}
          </div>

          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <History className="h-4 w-4" aria-hidden />
                Laatste wijzigingen
              </CardTitle>
              <CardDescription>De 25 meest recente niveauwijzigingen.</CardDescription>
            </CardHeader>
            <CardContent>
              {logs.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Nog geen wijzigingen.
                </p>
              ) : (
                <ul className="space-y-3 text-sm">
                  {logs.map((log) => (
                    <li key={log.id} className="border-b border-border pb-3 last:border-0">
                      <p className="text-foreground">
                        {log.item} → <span className="capitalize">{log.niveauStap}</span>
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {formatteerDatum(log.moment.slice(0, 10))} · {log.door}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
