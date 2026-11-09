import type { ForecastRequest, ForecastResult, GroupValue, SavedSession } from "./types";

function download(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function baseName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_") || "serie";
}

export function downloadSession(
  fileName: string,
  request: ForecastRequest,
  groupValues: GroupValue[] | null,
  result: ForecastResult,
): void {
  const session: SavedSession = {
    app: "timestral-forecast",
    version: 1,
    saved_at: new Date().toISOString(),
    file_name: fileName,
    request,
    group_values: groupValues,
    result,
  };
  download(`${baseName(fileName)}_timestral.json`, JSON.stringify(session, null, 2), "application/json");
}

function csvCell(v: string | number | null): string {
  if (v === null) return "";
  const s = String(v);
  return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV con separatore ";" e virgola decimale, come lo apre Excel in italiano. */
export function downloadForecastCsv(fileName: string, result: ForecastResult): void {
  const header = ["modello", "t", "p10", "p50", "p90"];
  const lines = [header.join(";")];
  const num = (x: number | null) => (x === null ? "" : String(x).replace(".", ","));
  for (const [model, m] of Object.entries(result.models)) {
    for (const f of m.forecast) {
      lines.push([model, f.t, num(f.p10), num(f.p50), num(f.p90)].map(csvCell).join(";"));
    }
  }
  download(`${baseName(fileName)}_previsioni.csv`, "﻿" + lines.join("\n") + "\n", "text/csv;charset=utf-8");
}

/** Valida un JSON salvato in precedenza; lancia un errore leggibile se non è compatibile. */
export function parseSession(text: string): SavedSession {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("Il file non è un JSON valido.");
  }
  const s = data as Partial<SavedSession>;
  if (!s || s.app !== "timestral-forecast" || !s.result?.meta || !s.result.models || !s.request) {
    throw new Error("Il JSON non è un risultato salvato da questa app.");
  }
  if (s.version !== 1) throw new Error(`Versione del file non supportata (${String(s.version)}).`);
  if (Object.keys(s.result.models).length === 0) throw new Error("Il JSON salvato non contiene modelli.");
  return s as SavedSession;
}
