"use client";

import { useEffect, useMemo, useState } from "react";
import { inspectGroups } from "@/lib/api";
import { COLUMN_TYPE_LABELS, fmtInt } from "@/lib/format";
import type { Aggregation, ForecastRequest, GroupValue, InspectResponse, ModelInfo } from "@/lib/types";
import { Button, Card, ErrorBox, Field, Notice, Skeleton, cx, inputClass } from "./ui";

const NUMERIC = new Set(["integer", "float"]);
const HEAVY_MB = 400;

export function MappingStep({
  inspect,
  models,
  initial,
  onSubmit,
  onBack,
}: {
  inspect: InspectResponse;
  models: ModelInfo[] | null;
  /** Scelte di un tentativo precedente (per esempio finito in errore), da ripristinare. */
  initial: ForecastRequest | null;
  onSubmit: (req: ForecastRequest, groupValues: GroupValue[] | null) => void;
  onBack: () => void;
}) {
  const [timeCol, setTimeCol] = useState(initial?.time_col ?? inspect.suggested_time_col ?? "");
  const [valueCol, setValueCol] = useState(initial?.value_col ?? inspect.suggested_value_col ?? "");
  const [groupCol, setGroupCol] = useState(initial ? (initial.group_col ?? "") : (inspect.suggested_group_col ?? ""));
  const [groups, setGroups] = useState<{ col: string; values: GroupValue[] } | null>(null);
  const [groupError, setGroupError] = useState<string | null>(null);
  const [groupValue, setGroupValue] = useState("");
  const [aggregation, setAggregation] = useState<Aggregation>(initial?.aggregation ?? "sum");
  const [sizes, setSizes] = useState<string[]>(initial?.models ?? ["Timestral-5M", "Timestral-28M"]);
  const [horizon, setHorizon] = useState(initial?.horizon ?? inspect.suggested_horizon);
  const [windows, setWindows] = useState(initial?.backtest_windows ?? 10);
  const preferredGroup = initial?.group_value ?? null;

  useEffect(() => {
    if (!groupCol) return;
    let cancelled = false;
    inspectGroups(inspect.file_id, groupCol)
      .then((r) => {
        if (cancelled) return;
        const values = r.group_values ?? [];
        setGroups({ col: groupCol, values });
        setGroupError(null);
        const keep = values.find((g) => g.value === preferredGroup);
        setGroupValue(keep ? keep.value : (values[0]?.value ?? ""));
      })
      .catch((e: Error) => !cancelled && setGroupError(e.message));
    return () => {
      cancelled = true;
    };
  }, [groupCol, inspect.file_id, preferredGroup]);

  const groupValues = groups && groups.col === groupCol ? groups.values : null;
  const loadingGroups = Boolean(groupCol) && !groupValues && !groupError;
  const columns = inspect.columns.map((c) => c.name);
  const heavy = (models ?? []).filter((m) => sizes.includes(m.name) && m.weight_mb >= HEAVY_MB);
  const toDownload = (models ?? []).filter((m) => sizes.includes(m.name) && !m.cached);

  const problems = useMemo(() => {
    const p: string[] = [];
    if (!timeCol) p.push("Scegli la colonna del tempo.");
    if (!valueCol) p.push("Scegli il valore da prevedere.");
    if (timeCol && timeCol === valueCol) p.push("Tempo e valore devono essere colonne diverse.");
    if (groupCol && (groupCol === timeCol || groupCol === valueCol))
      p.push("La colonna di raggruppamento deve essere diversa da tempo e valore.");
    if (groupCol && !groupValue) p.push("Scegli il gruppo da analizzare.");
    if (sizes.length === 0) p.push("Scegli almeno una taglia del modello.");
    if (!(horizon >= 1 && horizon <= 1000)) p.push("L'orizzonte deve essere tra 1 e 1000 passi.");
    if (!(windows >= 1 && windows <= 50)) p.push("Le finestre di backtest devono essere tra 1 e 50.");
    return p;
  }, [timeCol, valueCol, groupCol, groupValue, sizes, horizon, windows]);

  function submit() {
    if (problems.length) return;
    onSubmit(
      {
        file_id: inspect.file_id,
        time_col: timeCol,
        value_col: valueCol,
        group_col: groupCol || null,
        group_value: groupCol ? groupValue : null,
        aggregation,
        models: sizes,
        horizon,
        backtest_windows: windows,
      },
      groupCol ? groupValues : null,
    );
  }

  return (
    <div className="space-y-4">
      <Card
        title={`Anteprima · ${inspect.file_name}`}
        aside={`${fmtInt(inspect.n_rows)} righe · ${inspect.columns.length} colonne · prime ${inspect.preview.length}`}
      >
        <div className="max-h-96 overflow-auto rounded-lg border border-line">
          <table className="w-full min-w-max border-collapse text-sm">
            <thead className="sticky top-0 bg-surface-2">
              <tr>
                {inspect.columns.map((c) => (
                  <th key={c.name} className="border-b border-line px-3 py-2 text-left align-bottom">
                    <div
                      className={cx(
                        "font-semibold",
                        c.name === timeCol && "text-accent",
                        c.name === valueCol && "text-good",
                      )}
                    >
                      {c.name}
                    </div>
                    <div className="text-xs font-normal text-muted">
                      {COLUMN_TYPE_LABELS[c.type] ?? c.type}
                      {c.n_missing > 0 && ` · ${fmtInt(c.n_missing)} vuoti`}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {inspect.preview.map((row, i) => (
                <tr key={i} className="odd:bg-surface even:bg-surface-2/40">
                  {columns.map((c) => (
                    <td key={c} className="num whitespace-nowrap border-b border-line px-3 py-1.5">
                      {row[c] === null || row[c] === undefined ? (
                        <span className="text-muted">—</span>
                      ) : (
                        String(row[c])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="2 · Mappatura delle colonne">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Colonna del tempo *">
              <select className={inputClass} value={timeCol} onChange={(e) => setTimeCol(e.target.value)}>
                <option value="">— scegli —</option>
                {inspect.columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({COLUMN_TYPE_LABELS[c.type] ?? c.type})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Valore da prevedere *">
              <select className={inputClass} value={valueCol} onChange={(e) => setValueCol(e.target.value)}>
                <option value="">— scegli —</option>
                {inspect.columns
                  .filter((c) => c.name !== timeCol)
                  .map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({COLUMN_TYPE_LABELS[c.type] ?? c.type}
                      {NUMERIC.has(c.type) ? "" : ", non numerica"})
                    </option>
                  ))}
              </select>
            </Field>
            <Field
              label="Colonna di raggruppamento"
              hint="Facoltativa: se il file contiene più serie (per prodotto, sensore, squadra…)."
            >
              <select className={inputClass} value={groupCol} onChange={(e) => setGroupCol(e.target.value)}>
                <option value="">Nessuna (una sola serie)</option>
                {inspect.columns
                  .filter((c) => c.name !== timeCol && c.name !== valueCol)
                  .map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({fmtInt(c.n_unique)} valori)
                    </option>
                  ))}
              </select>
            </Field>
            {groupCol ? (
              <Field label="Gruppo da analizzare *">
                {loadingGroups ? (
                  <Skeleton className="h-9.5 w-full" />
                ) : (
                  <select
                    className={inputClass}
                    value={groupValue}
                    onChange={(e) => setGroupValue(e.target.value)}
                  >
                    {(groupValues ?? []).map((g) => (
                      <option key={g.value} value={g.value}>
                        {g.value} ({fmtInt(g.count)} righe)
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            ) : (
              <div />
            )}
            <Field label="Righe sullo stesso istante" hint="Come aggregare i duplicati.">
              <select
                className={inputClass}
                value={aggregation}
                onChange={(e) => setAggregation(e.target.value as Aggregation)}
              >
                <option value="sum">Somma</option>
                <option value="mean">Media</option>
              </select>
            </Field>
          </div>
          {groupError && (
            <div className="mt-3">
              <ErrorBox message={groupError} />
            </div>
          )}
        </Card>

        <Card title="3 · Impostazioni">
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Taglie di Timestral da confrontare</legend>
            {models === null ? (
              <div className="grid grid-cols-2 gap-2">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-14" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {models.map((m) => {
                  const on = sizes.includes(m.name);
                  return (
                    <label
                      key={m.name}
                      className={cx(
                        "flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-sm",
                        on ? "border-accent bg-surface-2" : "border-line",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 accent-(--accent)"
                        checked={on}
                        onChange={() =>
                          setSizes((s) =>
                            on
                              ? s.filter((x) => x !== m.name)
                              : models.map((x) => x.name).filter((x) => x === m.name || s.includes(x)),
                          )
                        }
                      />
                      <span>
                        <span className="font-medium">{m.size}</span>
                        <span className="block text-xs text-muted">
                          ~{fmtInt(m.weight_mb)} MB · {m.cached ? "in cache" : "da scaricare"}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </fieldset>
          {heavy.length > 0 && (
            <div className="mt-3">
              <Notice>
                Le taglie grandi ({heavy.map((m) => m.size).join(", ")}) sono più lente, soprattutto senza GPU.
              </Notice>
            </div>
          )}
          {toDownload.length > 0 && (
            <div className="mt-3">
              <Notice>
                Al primo uso verranno scaricati da Hugging Face i pesi di{" "}
                {toDownload.map((m) => `${m.size} (~${fmtInt(m.weight_mb)} MB)`).join(", ")}: può richiedere
                alcuni minuti.
              </Notice>
            </div>
          )}
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="Orizzonte di previsione" hint="Quanti passi futuri prevedere.">
              <input
                type="number"
                min={1}
                max={1000}
                className={inputClass}
                value={Number.isFinite(horizon) ? horizon : ""}
                onChange={(e) => setHorizon(e.target.valueAsNumber)}
              />
            </Field>
            <Field label="Finestre di backtest" hint="Massimo 50; si usano quelle che entrano nella serie.">
              <input
                type="number"
                min={1}
                max={50}
                className={inputClass}
                value={Number.isFinite(windows) ? windows : ""}
                onChange={(e) => setWindows(e.target.valueAsNumber)}
              />
            </Field>
          </div>
        </Card>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack}>
          ← Cambia file
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          {problems.length > 0 && <span className="text-sm text-muted">{problems[0]}</span>}
          <Button variant="primary" onClick={submit} disabled={problems.length > 0}>
            Avvia la previsione
          </Button>
        </div>
      </div>
    </div>
  );
}
