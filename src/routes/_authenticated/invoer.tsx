import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useMemo, useState } from "react";
import {
  CalendarClock,
  CheckCircle2,
  Leaf,
  MapPin,
  Package,
  Scale,
  Sparkles,
} from "lucide-react";

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

function VeldGroep({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-5 sm:grid-cols-2">{children}</div>
  );
}

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
  const locatie = stamdata.locaties.find((l) => l.id === locatieId);

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
  const isHandmatigOverschreven =
    handmatigHoudbaar !== "" &&
    berekendHoudbaar !== null &&
    handmatigHoudbaar !== berekendHoudbaar;

  const geenStamdata =
    stamdata.producten.length === 0 || stamdata.locaties.length === 0;

  const kanVersturen =
    !bezig && !geenStamdata && hoeveelheid !== "" && Number(hoeveelheid.replace(",", ".")) > 0;

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
            className="mt-6 flex items-start gap-3 rounded-lg border border-success/40 bg-success/10 px-4 py-3 text-sm text-foreground"
          >
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
            <span>
              <span className="font-semibold text-success">Opgeslagen — </span>
              {bevestiging}
            </span>
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

        <form onSubmit={verstuur} className="mt-8 space-y-6">
          {/* ── Sectie 1: Product & conservering ────────────────────── */}
          <Card className="overflow-hidden">
            <CardHeader className="bg-surface/60 pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <Leaf className="h-4 w-4 text-primary" />
                Wat
              </CardTitle>
              <CardDescription className="text-xs">
                Kies het product en de conserveringsmethode.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-6">
              <VeldGroep>
                <div className="sm:col-span-2 space-y-2">
                  <Label htmlFor="product">Product</Label>
                  <Select
                    value={String(productId)}
                    onValueChange={(v) => setProductId(Number(v))}
                  >
                    <SelectTrigger id="product" className="h-11">
                      <SelectValue placeholder="Kies een product" />
                    </SelectTrigger>
                    <SelectContent>
                      {stamdata.producten.map((p) => (
                        <SelectItem key={p.id} value={String(p.id)}>
                          {p.naam}
                          {p.eenheid ? ` · ${p.eenheid}` : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="conservering">Conservering</Label>
                  <Select
                    value={conserveringId === null ? "vers" : String(conserveringId)}
                    onValueChange={(v) =>
                      setConserveringId(v === "vers" ? null : Number(v))
                    }
                  >
                    <SelectTrigger id="conservering" className="h-11">
                      <SelectValue placeholder="Vers" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="vers">Vers</SelectItem>
                      {stamdata.conserveringsmethoden.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.naam}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {termijn === null ? (
                      "Geen bewaartermijn bekend voor deze combinatie."
                    ) : (
                      <span className="inline-flex items-center gap-1.5">
                        <Sparkles className="h-3.5 w-3.5 text-warning" />
                        Bewaartermijn:{" "}
                        <Badge variant="secondary" className="font-medium">
                          {termijn} maand{termijn === 1 ? "" : "en"}
                        </Badge>
                      </span>
                    )}
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="hoeveelheid">
                    Hoeveelheid
                    {product?.eenheid ? (
                      <span className="ml-1 text-muted-foreground">
                        ({product.eenheid})
                      </span>
                    ) : null}
                  </Label>
                  <div className="relative">
                    <Scale className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="hoeveelheid"
                      className="h-11 pl-9 tnum"
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
                </div>
              </VeldGroep>
            </CardContent>
          </Card>

          {/* ── Sectie 2: Locatie ────────────────────────────────────── */}
          <Card className="overflow-hidden">
            <CardHeader className="bg-surface/60 pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <MapPin className="h-4 w-4 text-primary" />
                Waar
              </CardTitle>
              <CardDescription className="text-xs">
                Waar wordt deze partij opgeslagen?
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-6">
              <div className="space-y-2">
                <Label htmlFor="locatie">Locatie</Label>
                <Select
                  value={String(locatieId)}
                  onValueChange={(v) => setLocatieId(Number(v))}
                >
                  <SelectTrigger id="locatie" className="h-11">
                    <SelectValue placeholder="Kies een locatie" />
                  </SelectTrigger>
                  <SelectContent>
                    {stamdata.locaties.map((l) => (
                      <SelectItem key={l.id} value={String(l.id)}>
                        {l.naam}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          {/* ── Sectie 3: Datums ──────────────────────────────────────── */}
          <Card className="overflow-hidden">
            <CardHeader className="bg-surface/60 pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <CalendarClock className="h-4 w-4 text-primary" />
                Wanneer
              </CardTitle>
              <CardDescription className="text-xs">
                Oogstdatum en automatisch berekende houdbaarheidsdatum.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-6">
              <VeldGroep>
                <div className="space-y-2">
                  <Label htmlFor="datum">Oogstdatum</Label>
                  <Input
                    id="datum"
                    className="h-11 tnum"
                    type="date"
                    value={datum}
                    onChange={(e) => setDatum(e.target.value)}
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="houdbaar" className="flex items-center gap-2">
                    Houdbaar tot
                    {isHandmatigOverschreven ? (
                      <Badge variant="outline" className="text-[0.65rem] font-medium uppercase tracking-wide text-warning">
                        Handmatig
                      </Badge>
                    ) : null}
                  </Label>
                  <Input
                    id="houdbaar"
                    className="h-11 tnum"
                    type="date"
                    value={handmatigHoudbaar || berekendHoudbaar || ""}
                    onChange={(e) => setHandmatigHoudbaar(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {berekendHoudbaar
                      ? `Automatisch berekend op ${formatteerDatum(berekendHoudbaar)}. Overschrijf om aan te passen.`
                      : "Vul zelf een datum in, of laat leeg."}
                  </p>
                </div>
              </VeldGroep>
            </CardContent>
          </Card>

          {/* ── Sectie 4: Notitie ────────────────────────────────────── */}
          <Card className="overflow-hidden">
            <CardHeader className="bg-surface/60 pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <Package className="h-4 w-4 text-primary" />
                Notitie
              </CardTitle>
              <CardDescription className="text-xs">
                Optionele bijzonderheden over deze partij.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-6">
              <Textarea
                id="notitie"
                rows={3}
                placeholder="Bijvoorbeeld: laatste snee van het perceel."
                value={notitie}
                onChange={(e) => setNotitie(e.target.value)}
              />
            </CardContent>
          </Card>

          {/* ── Samenvatting & actie ──────────────────────────────────── */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-muted-foreground">
              {product ? (
                <span>
                  <span className="font-medium text-foreground">
                    {product.naam}
                  </span>
                  {hoeveelheid ? (
                    <> · {hoeveelheid} {product.eenheid}</>
                  ) : null}
                  {locatie ? <> · {locatie.naam}</> : null}
                  {effectiefHoudbaar ? (
                    <> · houdbaar tot {formatteerDatum(effectiefHoudbaar)}</>
                  ) : null}
                </span>
              ) : (
                <span>Oogstdatum {formatteerDatum(datum)}</span>
              )}
            </div>
            <Button
              type="submit"
              size="lg"
              disabled={!kanVersturen}
              className="sm:min-w-[200px]"
            >
              {bezig ? "Bezig…" : "Partij registreren"}
            </Button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}
