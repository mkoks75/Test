/** Datumhulpjes. Overal wordt met ISO-strings (YYYY-MM-DD) gewerkt. */

export type Urgentie = "verlopen" | "kritiek" | "let-op" | "ruim";

/** Vandaag als ISO-datum in de Nederlandse tijdzone. */
export function vandaag(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Amsterdam",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** Aantal hele dagen tussen `vanaf` en `isoDatum`. */
export function dagenTot(isoDatum: string, vanaf: string): number {
  const doel = Date.parse(`${isoDatum}T00:00:00Z`);
  const start = Date.parse(`${vanaf}T00:00:00Z`);
  return Math.round((doel - start) / 86_400_000);
}

/** Formatteer een ISO-datum als 19-08-2026. */
export function formatteerDatum(isoDatum: string): string {
  const [jaar = "", maand = "", dag = ""] = isoDatum.slice(0, 10).split("-");
  return `${dag}-${maand}-${jaar}`;
}

/** Tel maanden op bij een ISO-datum, met correctie voor kortere maanden. */
export function plusMaanden(isoDatum: string, maanden: number): string {
  const [jaarText = "1970", maandText = "01", dagText = "01"] = isoDatum
    .slice(0, 10)
    .split("-");
  const jaar = Number(jaarText);
  const maand = Number(maandText);
  const dag = Number(dagText);

  const totaal = maand - 1 + maanden;
  const nieuwJaar = jaar + Math.floor(totaal / 12);
  const nieuwMaand = (totaal % 12) + 1;
  const laatsteDag = new Date(Date.UTC(nieuwJaar, nieuwMaand, 0)).getUTCDate();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${nieuwJaar}-${pad(nieuwMaand)}-${pad(Math.min(dag, laatsteDag))}`;
}

export function urgentieVan(isoDatum: string, peildatum: string): Urgentie {
  const dagen = dagenTot(isoDatum, peildatum);
  if (dagen < 0) return "verlopen";
  if (dagen <= 2) return "kritiek";
  if (dagen <= 14) return "let-op";
  return "ruim";
}
