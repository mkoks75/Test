import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Boxes, MapPin, Package, Search } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { haalVoorraadData } from "@/lib/voorraad.functions";

export const Route = createFileRoute("/_authenticated/voorraad")({
  loader: () => haalVoorraadData(),
  head: () => ({
    meta: [
      { title: "Voorraad — MountainSense Farm" },
      {
        name: "description",
        content:
          "Alle open oogstpartijen met product, locatie, conservering, hoeveelheid en houdbaarheidsdatum.",
      },
      { property: "og:title", content: "Voorraad — MountainSense Farm" },
      {
        property: "og:description",
        content: "Alle open oogstpartijen op de boerderij, filterbaar per product en locatie.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: VoorraadPagina,
});

const urgentieStijl: Record<Urgentie, string> = {
  verlopen: "border-destructive/30 bg-destructive/12 text-destructive",
  kritiek: "border-accent/30 bg-accent/12 text-accent",
  "let-op": "border-warning/40 bg-warning/18 text-warning-foreground",
  ruim: "border-transparent bg-secondary text-secondary-foreground",
};

function VoorraadPagina() {
  const { peildatum, partijen, producten, locaties } = Route.useLoaderData();
  const [zoek, setZoek] = useState("");
  const [product, setProduct] = useState("alle");
  const [locatie, setLocatie] = useState("alle");

  const zichtbaar = useMemo(() => {
    const term = zoek.trim().toLowerCase();
    return partijen.filter((p) => {
      if (product !== "alle" && String(p.productId) !== product) return false;
      if (locatie !== "alle" && String(p.locatieId) !== locatie) return false;
      if (!term) return true;
      return `${p.product} ${p.locatie} ${p.conservering} ${p.notitie ?? ""}`
        .toLowerCase()
        .includes(term);
    });
  }, [partijen, product, locatie, zoek]);

  const totaalPartijen = zichtbaar.length;
  const totaalLocaties = new Set(zichtbaar.map((p) => p.locatieId)).size;
  const totaalProducten = new Set(zichtbaar.map((p) => p.productId)).size;

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
        <header className="mb-6">
          <h1 className="font-display text-3xl tracking-tight text-foreground">Voorraad</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Alle open partijen, gesorteerd op houdbaarheidsdatum.
          </p>
        </header>

        <div className="mb-6 grid gap-3 sm:grid-cols-3">
          {[
            { label: "Partijen", waarde: totaalPartijen, icon: Boxes },
            { label: "Producten", waarde: totaalProducten, icon: Package },
            { label: "Locaties", waarde: totaalLocaties, icon: MapPin },
          ].map((t) => (
            <Card key={t.label}>
              <CardContent className="flex items-center gap-3 py-4">
                <span className="grid h-10 w-10 place-items-center rounded-md bg-secondary text-secondary-foreground">
                  <t.icon className="h-5 w-5" aria-hidden />
                </span>
                <span>
                  <span className="block font-display text-2xl leading-none text-foreground">
                    {t.waarde}
                  </span>
                  <span className="text-xs text-muted-foreground">{t.label}</span>
                </span>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card>
          <CardHeader className="gap-4">
            <CardTitle className="text-base">Partijen</CardTitle>
            <div className="grid gap-3 sm:grid-cols-3">
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
                    placeholder="Product, locatie of notitie"
                    className="pl-9"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="filter-product">Product</Label>
                <Select value={product} onValueChange={setProduct}>
                  <SelectTrigger id="filter-product">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="alle">Alle producten</SelectItem>
                    {producten.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>
                        {p.naam}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="filter-locatie">Locatie</Label>
                <Select value={locatie} onValueChange={setLocatie}>
                  <SelectTrigger id="filter-locatie">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="alle">Alle locaties</SelectItem>
                    {locaties.map((l) => (
                      <SelectItem key={l.id} value={String(l.id)}>
                        {l.naam}
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
                Geen partijen gevonden met deze filters.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[42rem] text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3 font-medium">Product</th>
                      <th className="py-2 pr-3 font-medium">Conservering</th>
                      <th className="py-2 pr-3 font-medium">Locatie</th>
                      <th className="py-2 pr-3 text-right font-medium">Hoeveelheid</th>
                      <th className="py-2 pr-3 font-medium">Geoogst</th>
                      <th className="py-2 pr-3 font-medium">Houdbaar tot</th>
                      <th className="py-2 text-right font-medium">Etiket</th>

                    </tr>
                  </thead>
                  <tbody>
                    {zichtbaar.map((p) => {
                      const urgentie = p.houdbaarTot
                        ? urgentieVan(p.houdbaarTot, peildatum)
                        : null;
                      return (
                        <tr key={p.id} className="border-b border-border/60 last:border-0">
                          <td className="py-2.5 pr-3 font-medium text-foreground">
                            {p.product}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {p.conservering}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">{p.locatie}</td>
                          <td className="py-2.5 pr-3 text-right tabular-nums text-foreground">
                            {p.hoeveelheid} {p.eenheid}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {formatteerDatum(p.datum)}
                          </td>
                          <td className="py-2.5 pr-3">
                            {p.houdbaarTot && urgentie ? (
                              <Badge
                                variant="outline"
                                className={urgentieStijl[urgentie]}
                              >
                                {formatteerDatum(p.houdbaarTot)}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="py-2.5 text-right">
                            <Link
                              to="/etiket/$id"
                              params={{ id: String(p.id) }}
                              className="text-sm font-medium text-accent underline-offset-4 hover:underline"
                            >
                              Etiket
                            </Link>
                          </td>
                        </tr>

                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
