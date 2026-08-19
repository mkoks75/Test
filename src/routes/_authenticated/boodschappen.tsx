import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useMemo, useState } from "react";
import { Minus, Plus, PackageOpen, ShoppingCart, Search } from "lucide-react";

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
import { formatteerDatum, urgentieVan, type Urgentie } from "@/lib/datum";
import {
  haalBoodschappenData,
  openWinkelItem,
  pasVoorraadAan,
  voegWinkelItemToe,
} from "@/lib/winkel.functions";

export const Route = createFileRoute("/_authenticated/boodschappen")({
  loader: () => haalBoodschappenData(),
  head: () => ({
    meta: [
      { title: "Boodschappen — MountainSense Farm" },
      {
        name: "description",
        content:
          "Winkelvoorraad beheren: aantallen bijwerken, minimumvoorraad bewaken en producten openen.",
      },
      { property: "og:title", content: "Boodschappen — MountainSense Farm" },
      {
        property: "og:description",
        content: "Overzicht van de winkelvoorraad met aanvullijst en houdbaarheid.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: BoodschappenPagina,
});

const urgentieStijl: Record<Urgentie, string> = {
  verlopen: "border-destructive/30 bg-destructive/12 text-destructive",
  kritiek: "border-accent/30 bg-accent/12 text-accent",
  "let-op": "border-warning/40 bg-warning/18 text-warning-foreground",
  ruim: "border-transparent bg-secondary text-secondary-foreground",
};

function BoodschappenPagina() {
  const { peildatum, items, categorieen } = Route.useLoaderData();
  const router = useRouter();
  const wijzig = useServerFn(pasVoorraadAan);
  const open = useServerFn(openWinkelItem);
  const voegToe = useServerFn(voegWinkelItemToe);

  const [zoek, setZoek] = useState("");
  const [categorie, setCategorie] = useState("alle");
  const [alleenAanvullen, setAlleenAanvullen] = useState(false);
  const [bezig, setBezig] = useState(false);
  const [melding, setMelding] = useState<{ soort: "ok" | "fout"; tekst: string } | null>(
    null,
  );

  const [naam, setNaam] = useState("");
  const [merk, setMerk] = useState("");
  const [nieuweCategorie, setNieuweCategorie] = useState("");
  const [eenheid, setEenheid] = useState("stuks");
  const [voorraad, setVoorraad] = useState("1");
  const [minimum, setMinimum] = useState("");
  const [houdbaarTot, setHoudbaarTot] = useState("");

  const aanvullen = items.filter(
    (i) => i.minimumVoorraad !== null && i.voorraad <= i.minimumVoorraad,
  );

  const zichtbaar = useMemo(() => {
    const term = zoek.trim().toLowerCase();
    return items.filter((i) => {
      if (categorie !== "alle" && (i.categorie ?? "") !== categorie) return false;
      if (
        alleenAanvullen &&
        !(i.minimumVoorraad !== null && i.voorraad <= i.minimumVoorraad)
      )
        return false;
      if (!term) return true;
      return `${i.naam} ${i.merk ?? ""} ${i.categorie ?? ""} ${i.barcode ?? ""}`
        .toLowerCase()
        .includes(term);
    });
  }, [items, zoek, categorie, alleenAanvullen]);

  async function actie(fn: () => Promise<unknown>, tekst: string) {
    setBezig(true);
    setMelding(null);
    try {
      await fn();
      setMelding({ soort: "ok", tekst });
      await router.invalidate();
    } catch (fout) {
      setMelding({
        soort: "fout",
        tekst: fout instanceof Error ? fout.message : "Actie is niet gelukt.",
      });
    } finally {
      setBezig(false);
    }
  }

  async function opslaan(event: React.FormEvent) {
    event.preventDefault();
    if (!naam.trim()) return;
    const aantal = Number(voorraad.replace(",", "."));
    const min = minimum.trim() ? Number(minimum.replace(",", ".")) : null;
    await actie(
      () =>
        voegToe({
          data: {
            naam: naam.trim(),
            merk: merk.trim() ? merk.trim() : null,
            categorie: nieuweCategorie.trim() ? nieuweCategorie.trim() : null,
            eenheid: eenheid.trim() || "stuks",
            voorraad: Number.isFinite(aantal) ? Math.max(0, Math.round(aantal)) : 0,
            minimumVoorraad: min !== null && Number.isFinite(min) ? Math.round(min) : null,
            houdbaarTot: houdbaarTot || null,
            barcode: null,
          },
        }),
      `${naam.trim()} toegevoegd aan de winkelvoorraad.`,
    );
    setNaam("");
    setMerk("");
    setNieuweCategorie("");
    setVoorraad("1");
    setMinimum("");
    setHoudbaarTot("");
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
        <header className="mb-6">
          <h1 className="font-display text-3xl tracking-tight text-foreground">
            Boodschappen
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Winkelvoorraad in de kast: aantallen bijhouden, aanvullen en openen.
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
          <Card>
            <CardHeader className="gap-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle className="text-base">Winkelvoorraad</CardTitle>
                <Button
                  type="button"
                  variant={alleenAanvullen ? "default" : "outline"}
                  size="sm"
                  onClick={() => setAlleenAanvullen((v) => !v)}
                >
                  <ShoppingCart className="mr-2 h-4 w-4" aria-hidden />
                  Aanvullen ({aanvullen.length})
                </Button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="zoek">Zoeken</Label>
                  <div className="relative">
                    <Search
                      className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                      aria-hidden
                    />
                    <Input
                      id="zoek"
                      value={zoek}
                      onChange={(e) => setZoek(e.target.value)}
                      placeholder="Naam, merk of categorie"
                      className="pl-9"
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="filter-categorie">Categorie</Label>
                  <Select value={categorie} onValueChange={setCategorie}>
                    <SelectTrigger id="filter-categorie">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="alle">Alle categorieën</SelectItem>
                      {categorieen.map((c) => (
                        <SelectItem key={c} value={c}>
                          {c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {zichtbaar.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  Geen producten gevonden.
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {zichtbaar.map((item) => {
                    const laag =
                      item.minimumVoorraad !== null && item.voorraad <= item.minimumVoorraad;
                    return (
                      <li
                        key={item.id}
                        className="flex flex-wrap items-center gap-3 py-3"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-foreground">
                            {item.naam}
                            {item.merk ? (
                              <span className="text-muted-foreground"> · {item.merk}</span>
                            ) : null}
                          </p>
                          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            {item.categorie ? <span>{item.categorie}</span> : null}
                            {item.houdbaarTot ? (
                              <Badge
                                variant="outline"
                                className={urgentieStijl[urgentieVan(item.houdbaarTot, peildatum)]}
                              >
                                t/m {formatteerDatum(item.houdbaarTot)}
                              </Badge>
                            ) : null}
                            {laag ? (
                              <Badge variant="outline" className={urgentieStijl.kritiek}>
                                aanvullen
                              </Badge>
                            ) : null}
                          </p>
                        </div>

                        <div className="flex items-center gap-1.5">
                          <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            disabled={bezig || item.voorraad <= 0}
                            aria-label={`Eén ${item.naam} eraf`}
                            onClick={() =>
                              void actie(
                                () => wijzig({ data: { itemId: item.id, verschil: -1 } }),
                                `${item.naam} bijgewerkt.`,
                              )
                            }
                          >
                            <Minus className="h-4 w-4" aria-hidden />
                          </Button>
                          <span className="w-14 text-center text-sm tabular-nums text-foreground">
                            {item.voorraad} {item.eenheid}
                          </span>
                          <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            disabled={bezig}
                            aria-label={`Eén ${item.naam} erbij`}
                            onClick={() =>
                              void actie(
                                () => wijzig({ data: { itemId: item.id, verschil: 1 } }),
                                `${item.naam} bijgewerkt.`,
                              )
                            }
                          >
                            <Plus className="h-4 w-4" aria-hidden />
                          </Button>
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={bezig || item.voorraad <= 0}
                            onClick={() =>
                              void actie(
                                () => open({ data: { itemId: item.id } }),
                                `${item.naam} staat nu bij Geopend.`,
                              )
                            }
                          >
                            <PackageOpen className="mr-2 h-4 w-4" aria-hidden />
                            Openen
                          </Button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="text-base">Product toevoegen</CardTitle>
              <CardDescription>Nieuw artikel in de winkelvoorraad.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-3" onSubmit={(e) => void opslaan(e)}>
                <div className="space-y-1.5">
                  <Label htmlFor="naam">Naam</Label>
                  <Input
                    id="naam"
                    value={naam}
                    onChange={(e) => setNaam(e.target.value)}
                    placeholder="Bijv. Olijfolie"
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="merk">Merk</Label>
                  <Input id="merk" value={merk} onChange={(e) => setMerk(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="categorie">Categorie</Label>
                  <Input
                    id="categorie"
                    value={nieuweCategorie}
                    onChange={(e) => setNieuweCategorie(e.target.value)}
                    placeholder="Bijv. Voorraadkast"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="aantal">Aantal</Label>
                    <Input
                      id="aantal"
                      inputMode="numeric"
                      value={voorraad}
                      onChange={(e) => setVoorraad(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="eenheid">Eenheid</Label>
                    <Input
                      id="eenheid"
                      value={eenheid}
                      onChange={(e) => setEenheid(e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="minimum">Minimum</Label>
                    <Input
                      id="minimum"
                      inputMode="numeric"
                      value={minimum}
                      onChange={(e) => setMinimum(e.target.value)}
                      placeholder="Optioneel"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="houdbaar">Houdbaar tot</Label>
                    <Input
                      id="houdbaar"
                      type="date"
                      value={houdbaarTot}
                      onChange={(e) => setHoudbaarTot(e.target.value)}
                    />
                  </div>
                </div>
                <Button type="submit" className="w-full" disabled={bezig || !naam.trim()}>
                  Toevoegen
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
