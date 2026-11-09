"use client";

import { useMemo, useState } from "react";
import { fmt } from "@/lib/format";
import type { BacktestRow, ForecastRow } from "@/lib/types";
import { cx } from "./ui";

type SortKey = "origin" | "t" | "step" | "y" | "p10" | "p50" | "p90" | "err" | string;

const th = "border-b border-line px-3 py-2 text-left font-semibold whitespace-nowrap";
const td = "border-b border-line px-3 py-1.5 whitespace-nowrap";

function outside(r: BacktestRow): boolean {
  return r.y !== null && r.p10 !== null && r.p90 !== null && (r.y < r.p10 || r.y > r.p90);
}

export function BacktestTable({
  rows,
  baselines,
  baselineLabels,
  digits,
}: {
  rows: BacktestRow[];
  baselines: string[];
  baselineLabels: Record<string, string>;
  digits: number;
}) {
  const f = (x: number | null) => fmt(x, digits);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "t", dir: 1 });

  const sorted = useMemo(() => {
    const value = (r: BacktestRow): string | number | null => {
      if (sort.key === "err") return r.y !== null && r.p50 !== null ? Math.abs(r.y - r.p50) : null;
      return r[sort.key] ?? null;
    };
    const order = new Map(rows.map((r, i) => [r, i]));
    return [...rows].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (sort.key === "t" || sort.key === "origin") return ((order.get(a) ?? 0) - (order.get(b) ?? 0)) * sort.dir;
      if (va === null) return 1;
      if (vb === null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [rows, sort]);

  const columns: { key: SortKey; label: string; numeric?: boolean }[] = [
    { key: "origin", label: "Origine" },
    { key: "t", label: "Istante" },
    { key: "step", label: "Passo", numeric: true },
    { key: "y", label: "Reale", numeric: true },
    { key: "p10", label: "P10", numeric: true },
    { key: "p50", label: "P50", numeric: true },
    { key: "p90", label: "P90", numeric: true },
    { key: "err", label: "|Errore|", numeric: true },
    ...baselines.map((b) => ({ key: b, label: baselineLabels[b] ?? b, numeric: true })),
  ];

  function toggle(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }));
  }

  return (
    <div className="relative max-h-[28rem] overflow-auto rounded-lg border border-line">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={cx(th, c.numeric && "text-right")}
                aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
              >
                <button type="button" onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 hover:text-accent">
                  {c.label}
                  <span className="text-xs text-muted">{sort.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const out = outside(r);
            return (
              <tr key={`${r.origin}-${r.step}`} className="hover:bg-surface-2/60">
                <td className={td}>{r.origin}</td>
                <td className={td}>{r.t}</td>
                <td className={cx(td, "num text-right")}>{r.step}</td>
                <td
                  className={cx(td, "num text-right", out && "font-semibold text-bad")}
                  title={out ? "Fuori dall'intervallo P10–P90" : undefined}
                >
                  {f(r.y)}
                  {out && <span className="sr-only"> (fuori intervallo)</span>}
                </td>
                <td className={cx(td, "num text-right text-muted")}>{f(r.p10)}</td>
                <td className={cx(td, "num text-right")}>{f(r.p50)}</td>
                <td className={cx(td, "num text-right text-muted")}>{f(r.p90)}</td>
                <td className={cx(td, "num text-right")}>
                  {r.y !== null && r.p50 !== null ? f(Math.abs(r.y - r.p50)) : "—"}
                </td>
                {baselines.map((b) => (
                  <td key={b} className={cx(td, "num text-right text-muted")}>
                    {f(r[b] as number | null)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ForecastTable({ rows, digits }: { rows: ForecastRow[]; digits: number }) {
  const f = (x: number | null) => fmt(x, digits);
  return (
    <div className="relative max-h-[28rem] overflow-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-surface-2">
          <tr>
            <th className={th}>Istante</th>
            <th className={cx(th, "text-right")}>P10</th>
            <th className={cx(th, "text-right")}>P50</th>
            <th className={cx(th, "text-right")}>P90</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.t} className="hover:bg-surface-2/60">
              <td className={td}>{r.t}</td>
              <td className={cx(td, "num text-right text-muted")}>{f(r.p10)}</td>
              <td className={cx(td, "num text-right font-semibold")}>{f(r.p50)}</td>
              <td className={cx(td, "num text-right text-muted")}>{f(r.p90)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
