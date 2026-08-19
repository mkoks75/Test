import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";

import heroHarvest from "@/assets/hero-harvest.jpg";
import { haalHuidigeGebruiker, inloggen } from "@/lib/auth.functions";

export const Route = createFileRoute("/")({
  beforeLoad: async () => {
    const gebruiker = await haalHuidigeGebruiker();
    if (gebruiker) throw redirect({ to: "/dashboard" });
  },
  head: () => ({
    meta: [
      { title: "Inloggen — MountainSense Farm voorraad" },
      {
        name: "description",
        content:
          "Log in op het voorraadsysteem van MountainSense Farm om oogst te registreren en de voorraad te beheren.",
      },
      { property: "og:title", content: "Inloggen — MountainSense Farm voorraad" },
      {
        property: "og:description",
        content:
          "Toegang tot het voorraadsysteem van MountainSense Farm: oogst, houdbaarheid en uitgifte.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: InlogPagina,
});

const veldClasses =
  "w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/25";

const labelClasses =
  "mb-1.5 block text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground";

function InlogPagina() {
  const router = useRouter();
  const login = useServerFn(inloggen);
  const [gebruikersnaam, setGebruikersnaam] = useState("");
  const [wachtwoord, setWachtwoord] = useState("");
  const [fout, setFout] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);

  async function verstuur(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBezig(true);
    setFout(null);
    try {
      const uitkomst = await login({ data: { gebruikersnaam, wachtwoord } });
      if (uitkomst.ok) {
        await router.navigate({ to: "/dashboard" });
        return;
      }
      setFout(uitkomst.melding);
    } catch {
      setFout("Inloggen lukt nu niet. Is de database bereikbaar?");
    } finally {
      setBezig(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden lg:block">
        <img
          src={heroHarvest}
          alt="Kratten met pas geoogste wortelen, pastinaken en pompoenen in een boerenschuur"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-background via-background/40 to-transparent"
        />
        <div className="absolute bottom-0 left-0 p-10">
          <p className="max-w-sm font-display text-3xl leading-tight text-foreground">
            Alles van het land, tot op de dag nauwkeurig bijgehouden.
          </p>
        </div>
      </div>

      <div className="flex items-center justify-center px-4 py-16 sm:px-6">
        <div className="w-full max-w-sm">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="grid h-10 w-10 place-items-center rounded-md bg-primary font-display text-xl leading-none text-primary-foreground"
            >
              M
            </span>
            <span className="font-display text-xl leading-tight tracking-tight text-foreground">
              MountainSense
              <span className="block font-sans text-[0.68rem] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                Farm voorraad
              </span>
            </span>
          </div>

          <h1 className="mt-10 text-3xl tracking-tight text-foreground">
            Inloggen
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Meld je aan om de voorraad te bekijken en oogst te registreren.
          </p>

          {fout ? (
            <p
              role="alert"
              className="mt-6 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-foreground"
            >
              {fout}
            </p>
          ) : null}

          <form onSubmit={verstuur} className="mt-6 space-y-5">
            <div>
              <label htmlFor="gebruikersnaam" className={labelClasses}>
                Gebruikersnaam
              </label>
              <input
                id="gebruikersnaam"
                className={veldClasses}
                autoComplete="username"
                value={gebruikersnaam}
                onChange={(e) => setGebruikersnaam(e.target.value)}
                required
              />
            </div>

            <div>
              <label htmlFor="wachtwoord" className={labelClasses}>
                Wachtwoord
              </label>
              <input
                id="wachtwoord"
                className={veldClasses}
                type="password"
                autoComplete="current-password"
                value={wachtwoord}
                onChange={(e) => setWachtwoord(e.target.value)}
                required
              />
            </div>

            <button
              type="submit"
              disabled={bezig}
              className="w-full rounded-md bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {bezig ? "Bezig…" : "Inloggen"}
            </button>
          </form>

          <a
            href="/wachtwoord-vergeten"
            className="mt-5 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Wachtwoord vergeten?
          </a>
        </div>
      </div>
    </div>
  );
}
