import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Camera, CameraOff, ScanLine } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_authenticated/scan")({
  head: () => ({
    meta: [
      { title: "QR-code scannen — MountainSense Farm" },
      {
        name: "description",
        content:
          "Scan de QR-code op een etiket met de camera en open direct de bijbehorende voorraadpartij.",
      },
      { property: "og:title", content: "QR-code scannen — MountainSense Farm" },
      {
        property: "og:description",
        content: "Scan etiketten en open de bijbehorende partij in de voorraad.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: ScanPagina,
});

/** Haalt het partij-id uit een gescande waarde (URL of los nummer). */
function partijIdUit(tekst: string): number | null {
  const schoon = tekst.trim();
  const viaUrl = schoon.match(/etiket\/(\d+)/);
  if (viaUrl?.[1]) return Number(viaUrl[1]);
  if (/^\d+$/.test(schoon)) return Number(schoon);
  return null;
}

function ScanPagina() {
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const [actief, setActief] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [handmatig, setHandmatig] = useState("");

  function openPartij(waarde: string) {
    const id = partijIdUit(waarde);
    if (id === null) {
      setFout("Deze code hoort niet bij een voorraadpartij.");
      return;
    }
    stopRef.current?.();
    void navigate({ to: "/etiket/$id", params: { id: String(id) } });
  }

  useEffect(() => () => stopRef.current?.(), []);

  async function startScannen() {
    setFout(null);
    try {
      const { BrowserQRCodeReader } = await import("@zxing/browser");
      const reader = new BrowserQRCodeReader();
      const controls = await reader.decodeFromVideoDevice(
        undefined,
        videoRef.current ?? undefined,
        (resultaat) => {
          if (resultaat) openPartij(resultaat.getText());
        },
      );
      stopRef.current = () => {
        controls.stop();
        stopRef.current = null;
        setActief(false);
      };
      setActief(true);
    } catch {
      setFout(
        "De camera kon niet worden gestart. Geef toestemming voor cameragebruik of voer het nummer handmatig in.",
      );
      setActief(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-2xl px-4 py-10 sm:px-6 lg:py-14">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
          Scannen
        </p>
        <h1 className="mt-2 text-3xl tracking-tight text-foreground sm:text-4xl">
          QR-code scannen
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Richt de camera op de QR-code van een etiket. Zodra de code herkend
          wordt, opent de bijbehorende partij automatisch.
        </p>

        <Card className="mt-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ScanLine className="h-4 w-4 text-accent" /> Camera
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="overflow-hidden rounded-lg border border-border bg-surface">
              <video
                ref={videoRef}
                className="aspect-video w-full bg-black object-cover"
                muted
                playsInline
              />
            </div>

            {fout ? (
              <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-foreground">
                {fout}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-3">
              {actief ? (
                <Button type="button" variant="outline" onClick={() => stopRef.current?.()}>
                  <CameraOff className="mr-2 h-4 w-4" /> Stop camera
                </Button>
              ) : (
                <Button type="button" onClick={() => void startScannen()}>
                  <Camera className="mr-2 h-4 w-4" /> Start camera
                </Button>
              )}
            </div>

            <form
              className="flex flex-wrap items-end gap-3 border-t border-border pt-4"
              onSubmit={(e) => {
                e.preventDefault();
                openPartij(handmatig);
              }}
            >
              <div className="grow">
                <Label htmlFor="handmatig">Of voer een partijnummer in</Label>
                <Input
                  id="handmatig"
                  inputMode="numeric"
                  placeholder="bijv. 42"
                  value={handmatig}
                  onChange={(e) => setHandmatig(e.target.value)}
                  className="mt-1.5"
                />
              </div>
              <Button type="submit" variant="outline" disabled={handmatig.trim() === ""}>
                Openen
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
