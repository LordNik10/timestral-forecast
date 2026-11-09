"use client";

import type { ReactNode } from "react";
import { digitsFor, fmt as fmtAuto, fmtInt, fmtPct } from "@/lib/format";
import type { ForecastResult, GroupValue, JobResponse, ModelInfo } from "@/lib/types";
import { MainChart } from "./MainChart";
import { ProgressPanel } from "./ProgressPanel";
import { SizeComparison } from "./SizeComparison";
import { BacktestTable, ForecastTable } from "./Tables";
import { Button, Card, ErrorBox, Notice, cx, inputClass } from "./ui";

const SHORT_BASELINE: Record<string, (k: number) => string> = {
  naive: () => "il naive (ultimo valore)",
  mean_k: (k) => `la media delle ultime ${k} osservazioni`,
  seasonal_naive: () => "il naive stagionale",
};

const ALL_SIZES = ["Timestral-5M", "Timestral-28M", "Timestral-123M", "Timestral-209M"];

function Tile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "good" | "bad";
}) {
  return (
    <div
      className={cx(
        "rounded-xl border bg-surface p-4",
        tone === "good" ? "border-good/50" : tone === "bad" ? "border-bad/50" : "border-line",
      )}
    >
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p
        className={cx(
          "num mt-1.5 text-3xl leading-tight sm:text-4xl",
          tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : "text-ink",
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </div>
  );
}

export function Dashboard({
  result,
  fileName,
  selected,
  onSelectModel,
  groupValues,
  onSelectGroup,
  onNewDataset,
  onDownloadJson,
  onDownloadCsv,
  busyJob,
  error,
  onDismissError,
  models,
  fromSavedFile,
}: {
  result: ForecastResult;
  fileName: string;
  selected: string;
  onSelectModel: (name: string) => void;
  groupValues: GroupValue[] | null;
  onSelectGroup: (value: string) => void;
  onNewDataset: () => void;
  onDownloadJson: () => void;
  onDownloadCsv: () => void;
  busyJob: JobResponse | null | undefined;
  error: string | null;
  onDismissError: () => void;
  models: ModelInfo[] | null;
  fromSavedFile: boolean;
}) {
  const { meta } = result;
  const digits = digitsFor(result.history.map((h) => h.y));
  const fmt = (x: number | null | undefined, d: number = digits) => fmtAuto(x, d);
  const model = result.models[selected] ?? Object.values(result.models)[0];
  const modelName = result.models[selected] ? selected : Object.keys(result.models)[0];
  const m = model.metrics.model;
  const baselineMaes = result.baselines
    .map((b) => ({ name: b, mae: model.metrics[b]?.mae ?? null }))
    .filter((b): b is { name: string; mae: number } => b.mae !== null);
  const best = baselineMaes.reduce<{ name: string; mae: number } | null>(
    (acc, b) => (acc === null || b.mae < acc.mae ? b : acc),
    null,
  );
  const beats = best !== null && m.mae !== null ? m.mae < best.mae : null;
  const first = model.forecast[0];
  const busy = busyJob !== undefined;
  const series = [meta.value_col, meta.group ? `${meta.group_col} = ${meta.group}` : null].filter(Boolean).join(" · ");
  const short = meta.n_obs < 30;

  return (
    <div className="space-y-4">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="truncate text-sm text-muted">
            {fileName} · frequenza {meta.frequency_label} · {fmtInt(meta.n_obs)} punti
            {meta.n_missing > 0 && `, ${fmtInt(meta.n_missing)} mancanti`}
          </p>
          <h1 className="num mt-1 text-3xl leading-tight text-ink sm:text-4xl">{series}</h1>
          <p className="mt-2 max-w-3xl text-base text-ink">
            {best && m.mae !== null ? (
              <>
                Con {modelName} il modello{" "}
                <strong className={beats ? "text-good" : "text-bad"}>{beats ? "batte" : "non batte"}</strong> la
                baseline migliore, {SHORT_BASELINE[best.name]?.(meta.mean_k) ?? best.name}: errore medio{" "}
                <span className="num">{fmt(m.mae)}</span> contro <span className="num">{fmt(best.mae)}</span>.
              </>
            ) : (
              model.summary
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted">
            Taglia
            <select
              className={cx(inputClass, "w-auto")}
              value={modelName}
              onChange={(e) => onSelectModel(e.target.value)}
              disabled={busy}
            >
              {ALL_SIZES.map((name) => {
                const done = name in result.models;
                const info = models?.find((x) => x.name === name);
                return (
                  <option key={name} value={name}>
                    {name.replace("Timestral-", "")}
                    {done ? "" : ` — da calcolare${info && !info.cached ? ` (~${fmtInt(info.weight_mb)} MB)` : ""}`}
                  </option>
                );
              })}
            </select>
          </label>
          {meta.group_col && (
            <label className="flex flex-col gap-1 text-xs text-muted">
              {meta.group_col}
              <select
                className={cx(inputClass, "w-auto max-w-56")}
                value={meta.group ?? ""}
                onChange={(e) => onSelectGroup(e.target.value)}
                disabled={busy || !groupValues}
              >
                {(groupValues ?? [{ value: meta.group ?? "", count: 0 }]).map((g) => (
                  <option key={g.value} value={g.value}>
                    {g.value}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button onClick={onNewDataset} disabled={busy}>
            Nuovo dataset
          </Button>
        </div>
      </header>

      {error && <ErrorBox message={error} onClose={onDismissError} />}
      {busy && <ProgressPanel job={busyJob} title="Ricalcolo in corso" />}

      <div className={cx("space-y-4 transition-opacity", busy && "pointer-events-none opacity-50")}>
        <div className="grid grid-cols-1 gap-3 min-[400px]:grid-cols-2 lg:grid-cols-4">
          <Tile
            label={`MAE ${modelName}`}
            value={fmt(m.mae)}
            tone={beats === null ? undefined : beats ? "good" : "bad"}
            sub={
              best && m.mae !== null && best.mae > 0
                ? `${beats ? "−" : "+"}${fmtPct(Math.abs(m.mae - best.mae) / best.mae, 1)} rispetto alla baseline migliore`
                : `RMSE ${fmt(m.rmse)}`
            }
          />
          <Tile
            label="MAE baseline"
            value={
              <span className="flex flex-col gap-0.5 text-xl sm:text-2xl">
                {baselineMaes.map((b) => (
                  <span key={b.name} className="flex items-baseline justify-between gap-3">
                    <span className="font-sans text-xs text-muted">{result.baseline_labels[b.name]}</span>
                    <span className={cx(b.name === best?.name && "underline decoration-1 underline-offset-4")}>
                      {fmt(b.mae)}
                    </span>
                  </span>
                ))}
              </span>
            }
            sub="sottolineata la migliore"
          />
          <Tile
            label="Copertura 10–90%"
            value={fmtPct(m.coverage_80)}
            sub={`ampiezza media ${fmt(m.width_80)} · attesa 80%`}
          />
          <Tile
            label={`Prossimo passo · ${first?.t ?? ""}`}
            value={fmt(first?.p50)}
            sub={first ? `intervallo ${fmt(first.p10)} – ${fmt(first.p90)}` : undefined}
          />
        </div>

        {short && <Notice>Serie corta ({meta.n_obs} punti): interpretare le metriche con cautela.</Notice>}

        <Card
          title="Storico, backtest e previsioni"
          aside={`${meta.backtest_windows} finestre da ${meta.backtest_horizon} ${meta.backtest_horizon === 1 ? "passo" : "passi"} · orizzonte ${meta.horizon}`}
        >
          <MainChart result={result} model={model} digits={digits} />
        </Card>

        <div className="grid items-start gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3" title="Confronto tra taglie (MAE)" aside="linee tratteggiate: baseline">
            <SizeComparison result={result} selected={modelName} digits={digits} />
          </Card>
          <Card className="lg:col-span-2" title="Previsioni future" aside={modelName}>
            <ForecastTable rows={model.forecast} digits={digits} />
          </Card>
        </div>

        <Card title="Backtest" aside="ordinabile · in rosso i valori fuori da P10–P90">
          <BacktestTable
            rows={model.backtest}
            baselines={result.baselines}
            baselineLabels={result.baseline_labels}
            digits={digits}
          />
        </Card>

        <Card title="Esporta">
          <div className="flex flex-wrap gap-2">
            <Button onClick={onDownloadJson}>Scarica il risultato (JSON)</Button>
            <Button onClick={onDownloadCsv}>Scarica le previsioni (CSV)</Button>
          </div>
          <p className="mt-2 text-xs text-muted">
            Il JSON si può ricaricare dalla schermata iniziale per rivedere questa dashboard senza ricalcolare.
          </p>
        </Card>

        <details className="group rounded-xl border border-line bg-surface p-4 sm:p-5">
          <summary className="cursor-pointer text-sm font-semibold">Note, definizioni e avvisi</summary>
          <div className="mt-4 grid gap-6 text-sm lg:grid-cols-2">
            <div>
              <h3 className="font-semibold">Metriche</h3>
              <dl className="mt-2 space-y-2 text-muted">
                <div>
                  <dt className="inline font-medium text-ink">MAE</dt> — errore assoluto medio della mediana (P50)
                  sulle finestre di backtest.
                </div>
                <div>
                  <dt className="inline font-medium text-ink">RMSE</dt> — radice dell&apos;errore quadratico medio:
                  pesa di più gli errori grandi.
                </div>
                <div>
                  <dt className="inline font-medium text-ink">sMAPE</dt> — errore percentuale simmetrico (0–200%),
                  ignorando i punti con denominatore nullo.
                </div>
                <div>
                  <dt className="inline font-medium text-ink">MASE</dt> — MAE diviso per l&apos;errore del naive
                  {meta.season_length && result.baselines.includes("seasonal_naive") ? " stagionale" : ""} in-sample
                  sul contesto di ogni finestra: sotto 1 batte quel riferimento.
                </div>
                <div>
                  <dt className="inline font-medium text-ink">Copertura 10–90%</dt> — quota di valori reali dentro
                  l&apos;intervallo P10–P90; idealmente vicina all&apos;80%.
                </div>
                <div>
                  <dt className="inline font-medium text-ink">WQL</dt> — weighted quantile loss media sui{" "}
                  {meta.quantile_levels.length} quantili: valuta tutta la distribuzione prevista.
                </div>
              </dl>
              <table className="mt-4 w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-1 font-medium">{modelName}</th>
                    <th className="py-1 text-right font-medium">MAE</th>
                    <th className="py-1 text-right font-medium">RMSE</th>
                    <th className="py-1 text-right font-medium">sMAPE</th>
                    <th className="py-1 text-right font-medium">MASE</th>
                  </tr>
                </thead>
                <tbody className="num">
                  {[["Timestral", m] as const, ...result.baselines.map((b) => [result.baseline_labels[b], model.metrics[b]] as const)].map(
                    ([label, mm]) => (
                      <tr key={label} className="border-t border-line">
                        <td className="py-1 font-sans">{label}</td>
                        <td className="py-1 text-right">{fmt(mm?.mae)}</td>
                        <td className="py-1 text-right">{fmt(mm?.rmse)}</td>
                        <td className="py-1 text-right">{mm?.smape == null ? "—" : `${fmt(mm.smape, 1)}%`}</td>
                        <td className="py-1 text-right">{fmt(mm?.mase, 2)}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
              {m.wql !== null && (
                <p className="mt-2 text-xs text-muted">
                  WQL di {modelName}: <span className="num">{fmt(m.wql, 3)}</span>
                </p>
              )}
            </div>
            <div>
              <h3 className="font-semibold">Impostazioni dell&apos;analisi</h3>
              <ul className="mt-2 space-y-1 text-muted">
                <li>
                  Tempo: <span className="text-ink">{meta.time_col}</span> · valore:{" "}
                  <span className="text-ink">{meta.value_col}</span>
                  {meta.group_col && (
                    <>
                      {" "}
                      · gruppo: <span className="text-ink">{meta.group_col} = {meta.group}</span>
                    </>
                  )}
                </li>
                <li>
                  Frequenza rilevata: <span className="text-ink">{meta.frequency_label}</span>
                  {meta.season_length ? ` · stagionalità ${meta.season_length}` : " · nessuna stagionalità"}
                </li>
                <li>
                  Backtest: {meta.backtest_windows} finestre non sovrapposte da {meta.backtest_horizon}{" "}
                  {meta.backtest_horizon === 1 ? "passo" : "passi"} (richieste {meta.requested_windows})
                </li>
                <li>
                  Media mobile della baseline: ultime {meta.mean_k} osservazioni · duplicati aggregati con{" "}
                  {meta.aggregation === "sum" ? "somma" : "media"}
                </li>
                <li>
                  Dispositivo di calcolo: <span className="text-ink">{meta.device}</span>
                </li>
              </ul>
              {meta.warnings.length > 0 && (
                <>
                  <h3 className="mt-4 font-semibold">Avvisi</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
                    {meta.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </>
              )}
              {fromSavedFile && (
                <p className="mt-4 text-xs text-muted">
                  Dashboard ricaricata da un JSON salvato: per calcolare altre taglie o gruppi serve il file originale
                  ancora in memoria nel backend.
                </p>
              )}
            </div>
          </div>
        </details>
      </div>
    </div>
  );
}
