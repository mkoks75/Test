import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useMemo, useState } from "react";
import { CheckCircle2, PackageMinus, Users } from "lucide-react";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { formatteerDatum, vandaag } from "@/lib/datum";
import { haalUitgifte, registreerUitgifte } from "@/lib/voorraad.functions";

export const Route = createFileRoute("/_authenticated/uitgifte")({
  validateSearch: (zoek: Record<string, unknown>) => ({
    partij: typeof zoek["partij"] === "number" ? (zoek["partij"] as number) : undefined,
  }),
  loader: () => haalUitgifte(),
  head: () => ({
    meta: [
      { title: "Uitgifte — MountainSense Farm" },
      {
        name: "description",
        content:
          "Geef een oogstpartij uit aan een ontvanger en houd de resterende voorraad automatisch bij.",
      },
      { property: "og:title", content: "Uitgifte — MountainSense Farm" },
      {
        property: "og:description",
        content: "Oogstpartijen uitgeven aan ontvangers met automatische voorraadcorrectie.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: UitgiftePagina,
});

function UitgiftePagina() {
  const { peildatum, partijen, ontvangers, historie } = Route.useLoaderData();
  const zoek = Route.useSearch();
  const router = useRouter();
  const verstuur = useServerFn(registreerUitgifte);

  const [partijId, setPartijId] = useState(
    zoek.partij && partijen.some((p) => p.id === zoek.partij)
      ? String(zoek.partij)
      : "",
  );
  const [hoeveelheid, setHoeveelheid] = useState("");
  const [ontvanger, setOntvanger] = useState("");
  const [datum, setDatum] = useState(peildatum || vandaag());
  const [notitie, setNotitie] = useState("");
  const [bezig, setBezig] = useState(false);
  const [melding, setMelding] = useState<{ soort: "ok" | "fout"; tekst: string } | null>(
    null,
  );

  const partij = useMemo(
    () => partijen.find((p) => String(p.id) === partijId) ?? null,
    [partijen, partijId],
  );

  const ingevuldeHoeveelheid = Number(hoeveelheid.replace(",", "."));
  const geldig =
    partij !== null &&
    Number.isFinite(ingevuldeHoeveelheid) &&
    ingevuldeHoeveelheid > 0 &&
    ingevuldeHoeveelheid <= partij.hoeveelheid + 1e-9 &&
    ontvanger.trim().length > 0;

  async function opslaan(event: React.FormEvent) {
    event.preventDefault();
    if (!geldig || !partij) return;
    setBezig(true);
    setMelding(null);
    try {
      const resultaat = await verstuur({
        data: {
          partijId: partij.id,
          hoeveelheid: ingevuldeHoeveelheid,
          ontvanger: ontvanger.trim(),
          datum,
          notitie: notitie.trim() ? notitie.trim() : null,
        },
      });
      setMelding({
        soort: "ok",
        tekst:
          resultaat.restant > 0
            ? `Uitgifte vastgelegd. Nog ${resultaat.restant} ${partij.eenheid} over in deze partij.`
            : "Uitgifte vastgelegd. De partij is volledig uitgegeven.",
      });
      setPartijId("");
      setHoeveelheid("");
      setNotitie("");
      await router.invalidate();
    } catch (fout) {
      setMelding({
        soort: "fout",
        tekst: fout instanceof Error ? fout.message : "Opslaan is niet gelukt.",
      });
    } finally {
      setBezig(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto grid w-full max-w-7xl gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section>
          <header className="mb-6">
            <h1 className="font-display text-3xl tracking-tight text-foreground">Uitgifte</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Leg vast wat er uit de voorraad gaat en naar wie.
            </p>
          </header>

          <form onSubmit={opslaan}>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <PackageMinus className="h-4 w-4 text-primary" aria-hidden />
                  Wat gaat eruit
                </CardTitle>
                <CardDescription>
                  Kies een open partij; de resterende hoeveelheid wordt automatisch
                  bijgewerkt.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="partij">Partij</Label>
                  <Select value={partijId} onValueChange={setPartijId}>
                    <SelectTrigger id="partij">
                      <SelectValue placeholder="Kies een partij" />
                    </SelectTrigger>
                    <SelectContent>
                      {partijen.map((p) => (
                        <SelectItem key={p.id} value={String(p.id)}>
                          {p.product} · {p.conservering} · {p.locatie} — {p.hoeveelheid}{" "}
                          {p.eenheid}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {partij ? (
                    <p className="text-xs text-muted-foreground">
                      Beschikbaar: {partij.hoeveelheid} {partij.eenheid}
                      {partij.houdbaarTot
                        ? ` · houdbaar tot ${formatteerDatum(partij.houdbaarTot)}`
                        : ""}
                    </p>
                  ) : null}
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="hoeveelheid">Hoeveelheid</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        id="hoeveelheid"
                        inputMode="decimal"
                        value={hoeveelheid}
                        onChange={(e) => setHoeveelheid(e.target.value)}
                        placeholder="0"
                      />
                      <span className="text-sm text-muted-foreground">
                        {partij?.eenheid ?? ""}
                      </span>
                    </div>
                    {partij ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-auto px-0 text-xs"
                        onClick={() => setHoeveelheid(String(partij.hoeveelheid))}
                      >
                        Hele partij uitgeven
                      </Button>
                    ) : null}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="datum">Datum</Label>
                    <Input
                      id="datum"
                      type="date"
                      value={datum}
                      onChange={(e) => setDatum(e.target.value)}
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="ontvanger">Ontvanger</Label>
                  {ontvangers.length > 0 ? (
                    <Select value={ontvanger} onValueChange={setOntvanger}>
                      <SelectTrigger id="ontvanger">
                        <SelectValue placeholder="Kies een ontvanger" />
                      </SelectTrigger>
                      <SelectContent>
                        {ontvangers.map((o) => (
                          <SelectItem key={o.id} value={o.naam}>
                            {o.naam}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id="ontvanger"
                      value={ontvanger}
                      onChange={(e) => setOntvanger(e.target.value)}
                      placeholder="Naam van de ontvanger"
                    />
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="notitie">Notitie</Label>
                  <Textarea
                    id="notitie"
                    value={notitie}
                    onChange={(e) => setNotitie(e.target.value)}
                    placeholder="Optioneel"
                    rows={2}
                  />
                </div>

                {melding ? (
                  <p
                    className={
                      melding.soort === "ok"
                        ? "flex items-center gap-2 rounded-md bg-secondary px-3 py-2 text-sm text-secondary-foreground"
                        : "rounded-md bg-destructive/12 px-3 py-2 text-sm text-destructive"
                    }
                  >
                    {melding.soort === "ok" ? (
                      <CheckCircle2 className="h-4 w-4" aria-hidden />
                    ) : null}
                    {melding.tekst}
                  </p>
                ) : null}

                <Button type="submit" disabled={!geldig || bezig} className="w-full">
                  {bezig ? "Bezig…" : "Uitgifte vastleggen"}
                </Button>
              </CardContent>
            </Card>
          </form>
        </section>

        <section className="lg:pt-[5.5rem]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="h-4 w-4 text-primary" aria-hidden />
                Laatste uitgiftes
              </CardTitle>
              <CardDescription>De 50 meest recente uitgiftes.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {historie.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  Er is nog niets uitgegeven.
                </p>
              ) : (
                historie.map((r) => (
                  <div
                    key={r.id}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-sm"
                  >
                    <span className="flex-1 font-medium text-foreground">{r.product}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {r.hoeveelheid} {r.eenheid}
                    </span>
                    <Badge variant="outline">{r.ontvanger}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatteerDatum(r.datum)}
                    </span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </section>
      </div>
    </AppShell>
  );
}
