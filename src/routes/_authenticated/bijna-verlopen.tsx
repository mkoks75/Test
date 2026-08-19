import { Link, createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AlertTriangle, CalendarClock } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { dagenTot, formatteerDatum, urgentieVan, type Urgentie } from "@/lib/datum";
import { haalVoorraadData } from "@/lib/voorraad.functions";

export const Route = createFileRoute("/_authenticated/bijna-verlopen")({
  loader: () => haalVoorraadData(),
  head: () => ({
    meta: [
      { title: "Bijna verlopen — MountainSense Farm" },
      {
        name: "description",
        content:
          "Partijen die binnenkort verlopen of al over datum zijn, zodat er op tijd actie ondernomen kan worden.",
      },
      { property: "og:title", content: "Bijna verlopen — MountainSense Farm" },
      {
        property: "og:description",
        content: "Overzicht van oogstpartijen die binnenkort verlopen of al over datum zijn.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: BijnaVerlopenPagina,
});

const urgentieStijl: Record<Urgentie, string> = {
  verlopen: "border-destructive/30 bg-destructive/12 text-destructive",
  kritiek: "border-accent/30 bg-accent/12 text-accent",
  "let-op": "border-warning/40 bg-warning/18 text-warning-foreground",
  ruim: "border-transparent bg-secondary text-secondary-foreground",
};

const urgentieLabel: Record<Urgentie, string> = {
  verlopen: "Verlopen",
  kritiek: "Kritiek",
  "let-op": "Let op",
  ruim: "Ruim",
};

function BijnaVerlopenPagina() {
  const { peildatum, partijen } = Route.useLoaderData();
  const [venster, setVenster] = useState("14");

  const rijen = useMemo(() => {
    const dagen = Number(venster);
    return partijen
      .filter((p) => p.houdbaarTot !== null)
      .map((p) => ({
        ...p,
        houdbaarTot: p.houdbaarTot as string,
        resterend: dagenTot(p.houdbaarTot as string, peildatum),
      }))
      .filter((p) => p.resterend <= dagen)
      .sort((a, b) => a.resterend - b.resterend);
  }, [partijen, peildatum, venster]);

  const verlopen = rijen.filter((r) => r.resterend < 0).length;

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
        <header className="mb-6">
          <h1 className="font-display text-3xl tracking-tight text-foreground">
            Bijna verlopen
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Peildatum {formatteerDatum(peildatum)} — {rijen.length} partijen in beeld,{" "}
            {verlopen} al over datum.
          </p>
        </header>

        <Card>
          <CardHeader className="flex-row items-end justify-between gap-4 space-y-0">
            <CardTitle className="text-base">Actielijst</CardTitle>
            <div className="w-44 space-y-1.5">
              <Label htmlFor="venster">Termijn</Label>
              <Select value={venster} onValueChange={setVenster}>
                <SelectTrigger id="venster">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">Alleen verlopen</SelectItem>
                  <SelectItem value="7">Binnen 7 dagen</SelectItem>
                  <SelectItem value="14">Binnen 14 dagen</SelectItem>
                  <SelectItem value="30">Binnen 30 dagen</SelectItem>
                  <SelectItem value="90">Binnen 3 maanden</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {rijen.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                Niets dat binnen deze termijn verloopt. Mooi werk.
              </p>
            ) : (
              rijen.map((r) => {
                const urgentie = urgentieVan(r.houdbaarTot, peildatum);
                return (
                  <div
                    key={r.id}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3"
                  >
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-card text-muted-foreground">
                      {urgentie === "verlopen" ? (
                        <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden />
                      ) : (
                        <CalendarClock className="h-4 w-4" aria-hidden />
                      )}
                    </span>
                    <span className="min-w-40 flex-1">
                      <span className="block font-medium text-foreground">{r.product}</span>
                      <span className="block text-xs text-muted-foreground">
                        {r.conservering} · {r.locatie} · {r.hoeveelheid} {r.eenheid}
                      </span>
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {formatteerDatum(r.houdbaarTot)}
                    </span>
                    <Badge variant="outline" className={urgentieStijl[urgentie]}>
                      {r.resterend < 0
                        ? `${Math.abs(r.resterend)} dagen over datum`
                        : r.resterend === 0
                          ? "Vandaag"
                          : `Nog ${r.resterend} dagen`}
                      {urgentie === "verlopen" ? "" : ` · ${urgentieLabel[urgentie]}`}
                    </Badge>
                    <Button asChild size="sm" variant="outline">
                      <Link to="/uitgifte" search={{ partij: r.id }}>
                        Uitgeven
                      </Link>
                    </Button>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
