import { Outlet, createFileRoute, redirect } from "@tanstack/react-router";

import { haalHuidigeGebruiker } from "@/lib/auth.functions";

/**
 * Toegangspoort. Alles onder deze route vereist een geldige sessie; de
 * controle draait op de server, vóór het laden van gegevens.
 */
export const Route = createFileRoute("/_authenticated")({
  beforeLoad: async () => {
    const gebruiker = await haalHuidigeGebruiker();
    if (!gebruiker) throw redirect({ to: "/" });
    return { gebruiker };
  },
  component: () => <Outlet />,
});
