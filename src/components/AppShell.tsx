import { Link, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState, type ReactNode } from "react";

import { uitloggen } from "@/lib/auth.functions";

/**
 * Navigatie-schil voor de ingelogde omgeving. Onderdelen die nog niet zijn
 * overgezet staan als inactieve items in het menu, zodat de volledige
 * structuur zichtbaar blijft.
 */

const actieveLinks = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/invoer", label: "Invoer" },
  { to: "/uitgifte", label: "Uitgifte" },
  { to: "/voorraad", label: "Voorraad" },
  { to: "/bijna-verlopen", label: "Bijna verlopen" },
  { to: "/boodschappen", label: "Boodschappen" },
  { to: "/geopend", label: "Geopend" },
  { to: "/scan", label: "Scan" },
  { to: "/beheer", label: "Beheer" },

] as const;

const komendeLinks: string[] = [];

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const router = useRouter();
  const logUit = useServerFn(uitloggen);

  async function afmelden() {
    await logUit();
    await router.navigate({ to: "/", replace: true });
    await router.invalidate();
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-50 border-b border-border/70 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-6 px-4 sm:px-6">
          <Link
            to="/dashboard"
            className="flex shrink-0 items-center gap-2.5"
            onClick={() => setMenuOpen(false)}
          >
            <span
              aria-hidden
              className="grid h-9 w-9 place-items-center rounded-md bg-primary font-display text-lg leading-none text-primary-foreground"
            >
              M
            </span>
            <span className="font-display text-lg leading-tight tracking-tight text-foreground">
              MountainSense
              <span className="block font-sans text-[0.68rem] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                Farm voorraad
              </span>
            </span>
          </Link>

          <nav className="hidden flex-1 items-center gap-1 lg:flex">
            {actieveLinks.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                activeProps={{
                  className: "bg-secondary text-secondary-foreground",
                }}
                inactiveProps={{
                  className:
                    "text-muted-foreground hover:bg-surface hover:text-foreground",
                }}
                className="rounded-md px-3 py-2 text-sm font-medium transition-colors"
              >
                {link.label}
              </Link>
            ))}
            {komendeLinks.map((label) => (
              <span
                key={label}
                title="Nog niet overgezet"
                className="cursor-not-allowed rounded-md px-3 py-2 text-sm font-medium text-muted-foreground/45"
              >
                {label}
              </span>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              onClick={() => void afmelden()}
              className="hidden rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface hover:text-foreground sm:inline-block"
            >
              Uitloggen
            </button>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-label="Navigatiemenu"
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface lg:hidden"
            >
              Menu
            </button>
          </div>
        </div>

        {menuOpen ? (
          <nav className="border-t border-border bg-card px-4 pb-4 pt-2 lg:hidden">
            {actieveLinks.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                onClick={() => setMenuOpen(false)}
                activeProps={{
                  className: "bg-secondary text-secondary-foreground",
                }}
                inactiveProps={{ className: "text-foreground hover:bg-surface" }}
                className="block rounded-md px-3 py-2.5 text-sm font-medium"
              >
                {link.label}
              </Link>
            ))}
            {komendeLinks.map((label) => (
              <span
                key={label}
                className="block px-3 py-2.5 text-sm font-medium text-muted-foreground/45"
              >
                {label}
              </span>
            ))}
            <button
              type="button"
              onClick={() => void afmelden()}
              className="mt-1 block w-full rounded-md px-3 py-2.5 text-left text-sm font-medium text-foreground hover:bg-surface"
            >
              Uitloggen
            </button>
          </nav>
        ) : null}
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-border bg-surface">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-1 px-4 py-6 text-sm text-muted-foreground sm:px-6">
          <p>MountainSense Farm — voorraadbeheer</p>
        </div>
      </footer>
    </div>
  );
}
