import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { z } from "zod";

import { herstelWachtwoord } from "@/lib/auth.functions";

export const Route = createFileRoute("/wachtwoord-herstellen")({
  validateSearch: z.object({ token: z.string().catch("") }),
  head: () => ({
    meta: [
      { title: "Nieuw wachtwoord instellen — MountainSense Farm voorraad" },
      {
        name: "description",
        content:
          "Stel een nieuw wachtwoord in voor je account in het voorraadsysteem van MountainSense Farm.",
      },
      {
        property: "og:title",
        content: "Nieuw wachtwoord instellen — MountainSense Farm voorraad",
      },
      {
        property: "og:description",
        content: "Stel een nieuw wachtwoord in voor het voorraadsysteem.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: HerstelPagina,
});

const MINIMUM = 10;

function HerstelPagina() {
  const { token } = Route.useSearch();
  const router = useRouter();
  const herstel = useServerFn(herstelWachtwoord);
  const [wachtwoord, setWachtwoord] = useState("");
  const [herhaling, setHerhaling] = useState("");
  const [fout, setFout] = useState<string | null>(null);
  const [gelukt, setGelukt] = useState(false);
  const [bezig, setBezig] = useState(false);

  async function verstuur(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFout(null);
    if (wachtwoord !== herhaling) {
      setFout("De twee wachtwoorden zijn niet gelijk.");
      return;
    }
    setBezig(true);
    try {
      const uitkomst = await herstel({ data: { token, wachtwoord } });
      if (uitkomst.ok) {
        setGelukt(true);
        setTimeout(() => void router.navigate({ to: "/" }), 1500);
      } else {
        setFout(uitkomst.melding ?? "Herstellen is niet gelukt.");
      }
    } catch {
      setFout("Herstellen is niet gelukt. Vraag een nieuwe link aan.");
    } finally {
      setBezig(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl tracking-tight text-foreground">
          Nieuw wachtwoord
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Kies een wachtwoord van minimaal {MINIMUM} tekens.
        </p>

        {!token ? (
          <p
            role="alert"
            className="mt-6 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-foreground"
          >
            Deze link is onvolledig. Vraag een nieuwe herstel-link aan.
          </p>
        ) : gelukt ? (
          <p
            role="status"
            className="mt-6 rounded-lg border border-success/40 bg-success/10 px-4 py-3 text-sm text-foreground"
          >
            Gelukt. Je kunt nu inloggen met je nieuwe wachtwoord.
          </p>
        ) : (
          <form onSubmit={verstuur} className="mt-6 space-y-5">
            {fout ? (
              <p
                role="alert"
                className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-foreground"
              >
                {fout}
              </p>
            ) : null}

            <div>
              <label
                htmlFor="nieuw"
                className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
              >
                Nieuw wachtwoord
              </label>
              <input
                id="nieuw"
                type="password"
                autoComplete="new-password"
                minLength={MINIMUM}
                className="w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/25"
                value={wachtwoord}
                onChange={(e) => setWachtwoord(e.target.value)}
                required
              />
            </div>

            <div>
              <label
                htmlFor="herhaling"
                className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
              >
                Nogmaals
              </label>
              <input
                id="herhaling"
                type="password"
                autoComplete="new-password"
                minLength={MINIMUM}
                className="w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/25"
                value={herhaling}
                onChange={(e) => setHerhaling(e.target.value)}
                required
              />
            </div>

            <button
              type="submit"
              disabled={bezig}
              className="w-full rounded-md bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {bezig ? "Bezig…" : "Wachtwoord opslaan"}
            </button>
          </form>
        )}

        <Link
          to="/"
          className="mt-6 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Terug naar inloggen
        </Link>
      </div>
    </div>
  );
}
