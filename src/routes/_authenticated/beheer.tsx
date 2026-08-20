import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { Check, Plus, Settings2 } from "lucide-react";

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  bewaarHoudbaarheidsregel,
  haalBeheer,
  voegStamdataItemToe,
  wijzigStamdataItem,
} from "@/lib/beheer.functions";

export const Route = createFileRoute("/_authenticated/beheer")({
  loader: () => haalBeheer(),
  head: () => ({
    meta: [
      { title: "Beheer — MountainSense Farm" },
      {
        name: "description",
        content:
          "Stamdata beheren: producten, locaties, eenheden, conserveringsmethoden, ontvangers en bewaartermijnen.",
      },
      { property: "og:title", content: "Beheer — MountainSense Farm" },
      {
        property: "og:description",
        content: "Beheer de stamdata van het voorraadsysteem.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: BeheerPagina,
  errorComponent: BeheerFout,
  notFoundComponent: () => (
    <AppShell>
      <div className="mx-auto w-full max-w-2xl px-4 py-16 text-center">
        <h1 className="font-display text-2xl text-foreground">Beheer niet gevonden</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Deze pagina bestaat niet (meer).
        </p>
      </div>
    </AppShell>
  ),
});

function BeheerFout({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();
  const geenRechten = /beheerrecht|ingelogd/i.test(error.message);
  return (
    <AppShell>
      <div className="mx-auto w-full max-w-2xl px-4 py-16 text-center">
        <h1 className="font-display text-2xl text-foreground">
          {geenRechten ? "Geen toegang tot Beheer" : "Beheer kon niet laden"}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {geenRechten
            ? "Je account heeft geen beheerrechten. Vraag een beheerder om deze rechten toe te kennen."
            : error.message}
        </p>
        {geenRechten ? null : (
          <button
            type="button"
            className="mt-6 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            onClick={() => {
              void router.invalidate();
              reset();
            }}
          >
            Opnieuw proberen
          </button>
        )}
      </div>
    </AppShell>
  );
}

type Soort = "product" | "locatie" | "eenheid" | "conservering" | "ontvanger";
type Item = { id: number; naam: string; actief: boolean };

function BeheerPagina() {
  const data = Route.useLoaderData();
  const router = useRouter();
  const voegToe = useServerFn(voegStamdataItemToe);
  const wijzig = useServerFn(wijzigStamdataItem);
  const bewaarTermijn = useServerFn(bewaarHoudbaarheidsregel);

  const [bezig, setBezig] = useState(false);
  const [melding, setMelding] = useState<{ soort: "ok" | "fout"; tekst: string } | null>(
    null,
  );

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

  const tabbladen: Array<{ soort: Soort; label: string; items: Item[] }> = [
    { soort: "product", label: "Producten", items: data.producten },
    { soort: "locatie", label: "Locaties", items: data.locaties },
    { soort: "eenheid", label: "Eenheden", items: data.eenheden },
    { soort: "conservering", label: "Conservering", items: data.conserveringsmethoden },
    { soort: "ontvanger", label: "Ontvangers", items: data.ontvangers },
  ];

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        <header className="mb-6">
          <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight text-foreground">
            <Settings2 className="h-7 w-7 text-primary" aria-hidden />
            Beheer
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Stamdata van het systeem. Wijzigingen gelden direct voor alle schermen.
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

        <Tabs defaultValue="product">
          <TabsList className="mb-5 flex w-full flex-wrap justify-start">
            {tabbladen.map((t) => (
              <TabsTrigger key={t.soort} value={t.soort}>
                {t.label}
              </TabsTrigger>
            ))}
            <TabsTrigger value="houdbaarheid">Bewaartermijnen</TabsTrigger>
          </TabsList>

          {tabbladen.map((tab) => (
            <TabsContent key={tab.soort} value={tab.soort}>
              <StamdataLijst
                soort={tab.soort}
                label={tab.label}
                items={tab.items}
                bezig={bezig}
                onToevoegen={(naam) =>
                  actie(
                    () => voegToe({ data: { soort: tab.soort, naam, eenheidId: null } }),
                    `${naam} toegevoegd.`,
                  )
                }
                onWijzigen={(id, naam, actief) =>
                  actie(
                    () => wijzig({ data: { soort: tab.soort, id, naam, actief } }),
                    `${naam} opgeslagen.`,
                  )
                }
              />
            </TabsContent>
          ))}

          <TabsContent value="houdbaarheid">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Bewaartermijnen</CardTitle>
                <CardDescription>
                  Per combinatie van product en conserveringsmethode het aantal maanden
                  houdbaarheid. Dit vult de houdbaarheidsdatum bij oogstregistratie.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <TermijnFormulier
                  producten={data.producten}
                  methoden={data.conserveringsmethoden}
                  bezig={bezig}
                  onOpslaan={(invoer, omschrijving) =>
                    actie(() => bewaarTermijn({ data: invoer }), omschrijving)
                  }
                />

                {data.houdbaarheid.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    Nog geen bewaartermijnen ingesteld.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[30rem] text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                          <th className="py-2 pr-3 font-medium">Product</th>
                          <th className="py-2 pr-3 font-medium">Conservering</th>
                          <th className="py-2 pr-3 text-right font-medium">Maanden</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.houdbaarheid.map((h) => (
                          <tr key={h.id} className="border-b border-border/60 last:border-0">
                            <td className="py-2 pr-3 text-foreground">{h.product}</td>
                            <td className="py-2 pr-3 text-muted-foreground">
                              {h.conservering ?? "Alle methoden"}
                            </td>
                            <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                              {h.maanden}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}

function StamdataLijst({
  soort,
  label,
  items,
  bezig,
  onToevoegen,
  onWijzigen,
}: {
  soort: Soort;
  label: string;
  items: Item[];
  bezig: boolean;
  onToevoegen: (naam: string) => Promise<void>;
  onWijzigen: (id: number, naam: string, actief: boolean) => Promise<void>;
}) {
  const [nieuw, setNieuw] = useState("");
  const [namen, setNamen] = useState<Record<number, string>>({});

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{label}</CardTitle>
        <CardDescription>
          Inactieve items blijven bewaard maar verschijnen niet meer in keuzelijsten.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const naam = nieuw.trim();
            if (!naam) return;
            await onToevoegen(naam);
            setNieuw("");
          }}
        >
          <div className="min-w-[14rem] flex-1 space-y-1.5">
            <Label htmlFor={`nieuw-${soort}`}>Nieuw toevoegen</Label>
            <Input
              id={`nieuw-${soort}`}
              value={nieuw}
              onChange={(e) => setNieuw(e.target.value)}
              placeholder={`Naam van ${label.toLowerCase().replace(/s$/, "")}`}
            />
          </div>
          <Button type="submit" disabled={bezig || !nieuw.trim()}>
            <Plus className="mr-2 h-4 w-4" aria-hidden />
            Toevoegen
          </Button>
        </form>

        {items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Nog niets ingesteld.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => {
              const waarde = namen[item.id] ?? item.naam;
              const gewijzigd = waarde.trim() !== item.naam;
              return (
                <li key={item.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <Input
                    value={waarde}
                    aria-label={`Naam van ${item.naam}`}
                    onChange={(e) =>
                      setNamen((vorige) => ({ ...vorige, [item.id]: e.target.value }))
                    }
                    className="min-w-[12rem] flex-1"
                  />
                  <Badge variant={item.actief ? "secondary" : "outline"}>
                    {item.actief ? "actief" : "inactief"}
                  </Badge>
                  {gewijzigd ? (
                    <Button
                      type="button"
                      size="sm"
                      disabled={bezig || !waarde.trim()}
                      onClick={() =>
                        void onWijzigen(item.id, waarde.trim(), item.actief)
                      }
                    >
                      <Check className="mr-2 h-4 w-4" aria-hidden />
                      Opslaan
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={bezig}
                    onClick={() =>
                      void onWijzigen(item.id, waarde.trim() || item.naam, !item.actief)
                    }
                  >
                    {item.actief ? "Op inactief" : "Activeren"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function TermijnFormulier({
  producten,
  methoden,
  bezig,
  onOpslaan,
}: {
  producten: Item[];
  methoden: Item[];
  bezig: boolean;
  onOpslaan: (
    invoer: { productId: number; conserveringId: number | null; maanden: number },
    omschrijving: string,
  ) => Promise<void>;
}) {
  const [product, setProduct] = useState("");
  const [methode, setMethode] = useState("alle");
  const [maanden, setMaanden] = useState("");

  const aantal = Number(maanden);
  const geldig = product !== "" && Number.isFinite(aantal) && aantal >= 1;

  return (
    <form
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_8rem_auto] sm:items-end"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!geldig) return;
        await onOpslaan(
          {
            productId: Number(product),
            conserveringId: methode === "alle" ? null : Number(methode),
            maanden: Math.round(aantal),
          },
          "Bewaartermijn opgeslagen.",
        );
        setMaanden("");
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="termijn-product">Product</Label>
        <Select value={product} onValueChange={setProduct}>
          <SelectTrigger id="termijn-product">
            <SelectValue placeholder="Kies product" />
          </SelectTrigger>
          <SelectContent>
            {producten.map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {p.naam}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="termijn-methode">Conservering</Label>
        <Select value={methode} onValueChange={setMethode}>
          <SelectTrigger id="termijn-methode">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="alle">Alle methoden</SelectItem>
            {methoden.map((m) => (
              <SelectItem key={m.id} value={String(m.id)}>
                {m.naam}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="termijn-maanden">Maanden</Label>
        <Input
          id="termijn-maanden"
          inputMode="numeric"
          value={maanden}
          onChange={(e) => setMaanden(e.target.value)}
        />
      </div>
      <Button type="submit" disabled={bezig || !geldig}>
        Opslaan
      </Button>
    </form>
  );
}
