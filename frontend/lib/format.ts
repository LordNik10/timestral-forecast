import type { Num } from "./types";

const cache = new Map<string, Intl.NumberFormat>();

function formatter(min: number, max: number): Intl.NumberFormat {
  const key = `${min}-${max}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat("it-IT", { minimumFractionDigits: min, maximumFractionDigits: max });
    cache.set(key, f);
  }
  return f;
}

/** Numero in locale it-IT con decimali adattati all'ordine di grandezza. */
export function fmt(x: Num | undefined, digits?: number): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  if (digits !== undefined) return formatter(digits, digits).format(x);
  const abs = Math.abs(x);
  const d = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 1 ? 2 : 3;
  return formatter(0, d).format(x);
}

/** Decimali da usare per i valori di una serie, in base alla sua scala tipica (mediana dei valori assoluti). */
export function digitsFor(values: Num[]): number {
  const abs = values.filter((v): v is number => v !== null && Number.isFinite(v)).map(Math.abs).sort((a, b) => a - b);
  if (!abs.length) return 2;
  const median = abs[Math.floor(abs.length / 2)];
  return median >= 1000 ? 0 : median >= 100 ? 1 : median >= 1 ? 2 : 3;
}

export function fmtPct(x: Num | undefined, digits = 0): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return new Intl.NumberFormat("it-IT", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(x);
}

export function fmtInt(x: number): string {
  return formatter(0, 0).format(x);
}

export const COLUMN_TYPE_LABELS: Record<string, string> = {
  datetime: "data/ora",
  season: "stagione",
  year: "anno",
  integer: "intero",
  float: "decimale",
  boolean: "sì/no",
  text: "testo",
  empty: "vuota",
};

export const STAGE_LABELS: Record<string, string> = {
  queued: "In coda",
  preprocessing: "Preparazione della serie",
  loading_model: "Caricamento del modello",
  backtest: "Backtest",
  forecast: "Previsione",
  done: "Completato",
  error: "Errore",
};
