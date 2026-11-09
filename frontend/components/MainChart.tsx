"use client";

import { useMemo } from "react";
import {
  Area,
  Brush,
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import { fmt, fmt as fmtNum } from "@/lib/format";
import type { ForecastResult, ModelResult } from "@/lib/types";
import { useChartColors } from "@/lib/useChartColors";

interface Row {
  t: string;
  y?: number | null;
  bt?: number | null;
  btErr?: [number, number];
  btLo?: number | null;
  btHi?: number | null;
  fc?: number | null;
  band?: [number, number] | null;
  fcLo?: number | null;
  fcHi?: number | null;
  future?: boolean;
  baselines?: Record<string, number | null>;
}

function buildRows(result: ForecastResult, model: ModelResult): Row[] {
  const rows: Row[] = result.history.map((h) => ({ t: h.t, y: h.y }));
  const index = new Map(rows.map((r, i) => [r.t, i]));
  for (const b of model.backtest) {
    const i = index.get(b.t);
    if (i === undefined || b.p50 === null) continue;
    const r = rows[i];
    r.bt = b.p50;
    r.btLo = b.p10;
    r.btHi = b.p90;
    if (b.p10 !== null && b.p90 !== null) r.btErr = [b.p50 - b.p10, b.p90 - b.p50];
    r.baselines = Object.fromEntries(result.baselines.map((n) => [n, b[n] as number | null]));
  }
  // La linea tratteggiata parte dall'ultima osservazione, così previsione e storia si raccordano.
  const last = [...rows].reverse().find((r) => r.y !== null && r.y !== undefined);
  if (last && rows[rows.length - 1] === last && last.y != null) {
    last.fc = last.y;
    last.band = [last.y, last.y];
  }
  for (const f of model.forecast) {
    rows.push({
      t: f.t,
      fc: f.p50,
      fcLo: f.p10,
      fcHi: f.p90,
      band: f.p10 !== null && f.p90 !== null ? [f.p10, f.p90] : null,
      future: true,
    });
  }
  return rows;
}

function ChartTooltip({
  active,
  payload,
  label,
  baselineLabels,
  digits,
}: Partial<TooltipContentProps<number, string>> & { baselineLabels: Record<string, string>; digits: number }) {
  if (!active || !payload?.length) return null;
  const fmt = (x: number | null | undefined) => fmtNum(x, digits);
  const r = payload[0].payload as Row;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="mb-1 font-semibold text-ink">{label}</p>
      {r.y != null && (
        <p>
          Reale: <span className="num text-sm">{fmt(r.y)}</span>
        </p>
      )}
      {r.bt != null && (
        <>
          <p>
            Backtest P50: <span className="num text-sm">{fmt(r.bt)}</span>{" "}
            <span className="text-muted">
              (P10 {fmt(r.btLo)} – P90 {fmt(r.btHi)})
            </span>
          </p>
          {r.baselines &&
            Object.entries(r.baselines).map(([k, v]) => (
              <p key={k} className="text-muted">
                {baselineLabels[k] ?? k}: <span className="num">{fmt(v)}</span>
              </p>
            ))}
        </>
      )}
      {r.future && (
        <p>
          Previsione P50: <span className="num text-sm">{fmt(r.fc)}</span>{" "}
          <span className="text-muted">
            (P10 {fmt(r.fcLo)} – P90 {fmt(r.fcHi)})
          </span>
        </p>
      )}
    </div>
  );
}

export function MainChart({ result, model, digits }: { result: ForecastResult; model: ModelResult; digits: number }) {
  const colors = useChartColors();
  const rows = useMemo(() => buildRows(result, model), [result, model]);
  const nHist = result.history.length;
  const h = model.forecast.length;
  const long = nHist > Math.max(60, 5 * h);
  const startIndex = long ? Math.max(0, nHist - 5 * h) : 0;
  const firstFuture = model.forecast[0]?.t;
  const lastFuture = model.forecast[h - 1]?.t;

  return (
    <div className="h-80 w-full sm:h-96">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 16, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="t" minTickGap={24} tickLine={false} axisLine={{ stroke: colors.grid }} />
          <YAxis
            width={64}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => fmt(v)}
            domain={["auto", "auto"]}
          />
          {firstFuture && lastFuture && (
            <ReferenceArea
              x1={firstFuture}
              x2={lastFuture}
              fill={colors.zone}
              fillOpacity={0.06}
              ifOverflow="extendDomain"
              label={{ value: "previsioni", position: "insideTop", fill: colors.muted, fontSize: 12 }}
            />
          )}
          <Area
            dataKey="band"
            name="Intervallo P10–P90"
            stroke="none"
            fill={colors.band}
            fillOpacity={0.18}
            isAnimationActive={false}
            connectNulls={false}
            activeDot={false}
          />
          <Line
            dataKey="y"
            name="Storico"
            stroke={colors.history}
            strokeWidth={1.75}
            dot={nHist <= 60 ? { r: 2.5, fill: colors.history, strokeWidth: 0 } : false}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            dataKey="bt"
            name="Backtest (P50 e P10–P90)"
            stroke="none"
            dot={{ r: 3.5, fill: colors.backtest, stroke: colors.backtest }}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
            legendType="circle"
          >
            <ErrorBar dataKey="btErr" width={4} stroke={colors.backtest} strokeWidth={1.25} direction="y" />
          </Line>
          <Line
            dataKey="fc"
            name="Previsione P50"
            stroke={colors.model}
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={h <= 40 ? { r: 2.5, fill: colors.model, strokeWidth: 0 } : false}
            isAnimationActive={false}
          />
          <Tooltip content={<ChartTooltip baselineLabels={result.baseline_labels} digits={digits} />} />
          <Legend wrapperStyle={{ fontSize: 12, color: colors.muted }} />
          {long && (
            <Brush
              dataKey="t"
              height={24}
              startIndex={startIndex}
              endIndex={rows.length - 1}
              stroke={colors.model}
              fill="transparent"
              travellerWidth={8}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
