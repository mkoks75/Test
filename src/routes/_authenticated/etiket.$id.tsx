import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Printer, QrCode, ArrowLeft } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatteerDatum } from "@/lib/datum";
import { haalPartij } from "@/lib/voorraad.functions";

export const Route = createFileRoute("/_authenticated/etiket/$id")({
  head: () => ({
    meta: [
      { title: "Etiket printen — MountainSense Farm" },
      {
        name: "description",
        content:
          "Bekijk de partijgegevens en print een etiket met QR-code voor snelle herkenning in de opslag.",
      },
      { property: "og:title", content: "Etiket printen — MountainSense Farm" },
      {
        property: "og:description",
        content: "Partij-etiket met QR-code voor de voorraadadministratie.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  loader: async ({ params }) => {
    const partij = await haalPartij({ data: { id: Number(params.id) } });
    if (!partij) throw notFound();
    return partij;
  },
  component: EtiketPagina,
});

function EtiketPagina() {
  const partij = Route.useLoaderData();
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    const url = `${window.location.origin}/etiket/${partij.id}`;
    void QRCode.toDataURL(url, { width: 320, margin: 1 }).then(setQr);
  }, [partij.id]);

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 lg:py-14">
        <div className="print:hidden">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
            Etiket
          </p>
          <h1 className="mt-2 text-3xl tracking-tight text-foreground sm:text-4xl">
            {partij.product}
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Print dit etiket en plak het op de verpakking. Scan de QR-code later
            om deze partij direct terug te vinden.
          </p>
        </div>

        <Card className="mt-8 print:border-0 print:shadow-none">
          <CardHeader className="print:hidden">
            <CardTitle className="flex items-center gap-2 text-base">
              <QrCode className="h-4 w-4 text-accent" /> Etiket
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="etiket grid gap-6 sm:grid-cols-[1fr_auto]">
              <div>
                <p className="font-display text-2xl text-foreground">
                  {partij.product}
                </p>
                <dl className="mt-3 space-y-1.5 text-sm">
                  <Regel label="Volgnummer" waarde={partij.volgnummer ? `#${partij.volgnummer}` : `#${partij.id}`} />
                  <Regel label="Conservering" waarde={partij.conservering} />
                  <Regel label="Locatie" waarde={partij.locatie} />
                  <Regel
                    label="Hoeveelheid"
                    waarde={`${partij.hoeveelheid} ${partij.eenheid}`}
                  />
                  <Regel label="Geoogst" waarde={formatteerDatum(partij.datum)} />
                  <Regel
                    label="Houdbaar tot"
                    waarde={
                      partij.houdbaarTot
                        ? formatteerDatum(partij.houdbaarTot)
                        : "niet ingesteld"
                    }
                  />
                  {partij.notitie ? (
                    <Regel label="Notitie" waarde={partij.notitie} />
                  ) : null}
                </dl>
                {partij.uitgegeven ? (
                  <Badge variant="outline" className="mt-3 print:hidden">
                    Volledig uitgegeven
                  </Badge>
                ) : null}
              </div>

              <div className="flex items-start justify-center">
                {qr ? (
                  <img
                    src={qr}
                    alt={`QR-code voor partij ${partij.id} (${partij.product})`}
                    className="h-40 w-40"
                  />
                ) : (
                  <div className="h-40 w-40 animate-pulse rounded bg-muted" />
                )}
              </div>
            </div>

            <div className="mt-8 flex flex-wrap gap-3 print:hidden">
              <Button type="button" onClick={() => window.print()}>
                <Printer className="mr-2 h-4 w-4" /> Print etiket
              </Button>
              <Button asChild variant="outline">
                <Link to="/voorraad">
                  <ArrowLeft className="mr-2 h-4 w-4" /> Naar voorraad
                </Link>
              </Button>
              {!partij.uitgegeven ? (
                <Button asChild variant="outline">
                  <Link to="/uitgifte" search={{ partij: partij.id }}>
                    Uitgifte registreren
                  </Link>
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      <style>{`
        @media print {
          header, footer, nav { display: none !important; }
          body { background: #fff; }
          .etiket { max-width: 80mm; }
        }
      `}</style>
    </AppShell>
  );
}

function Regel({ label, waarde }: { label: string; waarde: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-32 shrink-0 font-medium text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{waarde}</dd>
    </div>
  );
}
