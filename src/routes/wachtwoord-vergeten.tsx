import { Link, createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";

import { vraagHerstelLink } from "@/lib/auth.functions";

export const Route = createFileRoute("/wachtwoord-vergeten")({
  head: () => ({
    meta: [
      { title: "Wachtwoord vergeten — MountainSense Farm voorraad" },
      {
        name: "description",
        content:
          "Vraag een herstel-link aan om opnieuw toegang te krijgen tot het voorraadsysteem van MountainSense Farm.",
      },
      {
        property: "og:title",
        content: "Wachtwoord vergeten — MountainSense Farm voorraad",
      },
      {
        property: "og:description",
        content: "Vraag een herstel-link aan voor het voorraadsysteem.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: VergetenPagina,
});

function VergetenPagina() {
  const vraagAan = useServerFn(vraagHerstelLink);
  const [email, setEmail] = useState("");
  const [verstuurd, setVerstuurd] = useState(false);
  const [bezig, setBezig] = useState(false);

  async function verstuur(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBezig(true);
    try {
      await vraagAan({ data: { email } });
    } catch {
      // Bewust stil: we tonen altijd dezelfde bevestiging.
    } finally {
      setVerstuurd(true);
      setBezig(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl tracking-tight text-foreground">
          Wachtwoord vergeten
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Vul je e-mailadres in. Is het bij ons bekend, dan sturen we een link
          waarmee je een nieuw wachtwoord instelt.
        </p>

        {verstuurd ? (
          <p
            role="status"
            className="mt-6 rounded-lg border border-success/40 bg-success/10 px-4 py-3 text-sm text-foreground"
          >
            Als dit adres bekend is, is er een herstel-link onderweg. De link is
            een uur geldig.
          </p>
        ) : (
          <form onSubmit={verstuur} className="mt-6 space-y-5">
            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
              >
                E-mailadres
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                className="w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/25"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <button
              type="submit"
              disabled={bezig}
              className="w-full rounded-md bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {bezig ? "Bezig…" : "Stuur herstel-link"}
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
