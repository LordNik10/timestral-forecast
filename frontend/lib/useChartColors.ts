"use client";

import { useMemo, useSyncExternalStore } from "react";

const KEYS = {
  history: "--chart-history",
  model: "--chart-model",
  band: "--chart-band",
  backtest: "--chart-backtest",
  zone: "--chart-zone",
  grid: "--chart-grid",
  selected: "--chart-selected",
  other: "--chart-other",
  muted: "--muted",
  ink: "--ink",
  bad: "--bad",
  good: "--good",
} as const;

export type ChartColors = Record<keyof typeof KEYS, string>;

const FALLBACK: ChartColors = {
  history: "#2b2a27",
  model: "#2f5d8a",
  band: "#2f5d8a",
  backtest: "#c0582b",
  zone: "#2f5d8a",
  grid: "#e4e1d8",
  selected: "#2f5d8a",
  other: "#b7c4d3",
  muted: "#6b675e",
  ink: "#1d1c19",
  bad: "#b3362b",
  good: "#1f7a4d",
};

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

/** Colori dei grafici letti dalle variabili CSS del tema corrente; si aggiornano al cambio di tema. */
export function useChartColors(): ChartColors {
  const theme = useSyncExternalStore(
    subscribe,
    () => (document.documentElement.classList.contains("dark") ? "dark" : "light"),
    () => "light",
  );
  return useMemo(() => {
    if (typeof window === "undefined") return FALLBACK;
    const style = getComputedStyle(document.documentElement);
    const out = { ...FALLBACK };
    for (const [k, v] of Object.entries(KEYS) as [keyof ChartColors, string][]) {
      out[k] = style.getPropertyValue(v).trim() || FALLBACK[k];
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- il tema è la dipendenza che cambia le variabili
  }, [theme]);
}
