"use client";

import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt } from "@/lib/format";
import type { ForecastResult } from "@/lib/types";
import { useChartColors } from "@/lib/useChartColors";

const DASHES = ["5 4", "2 3", "8 3 2 3"];

export function SizeComparison({
  result,
  selected,
  digits,
}: {
  result: ForecastResult;
  selected: string;
  digits: number;
}) {
  const colors = useChartColors();
  const data = Object.entries(result.models).map(([name, m]) => ({
    name: name.replace("Timestral-", ""),
    full: name,
    mae: m.metrics.model.mae,
  }));
  const ref = result.models[selected] ?? Object.values(result.models)[0];
  const baselines = result.baselines
    .map((b) => ({ name: b, label: result.baseline_labels[b] ?? b, mae: ref.metrics[b]?.mae ?? null }))
    .filter((b): b is { name: string; label: string; mae: number } => b.mae !== null);
  const max = Math.max(...data.map((d) => d.mae ?? 0), ...baselines.map((b) => b.mae)) * 1.1 || 1;

  return (
    <div>
      <div style={{ height: 56 + data.length * 44 }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 22, right: 24, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" domain={[0, max]} tickFormatter={(v: number) => fmt(v)} tickLine={false} />
            <YAxis type="category" dataKey="name" width={52} tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ fill: colors.grid, fillOpacity: 0.4 }}
              formatter={(v) => [fmt(Number(v), digits), "MAE"]}
              labelFormatter={(l) => `Timestral-${String(l)}`}
            />
            <Bar dataKey="mae" radius={[0, 4, 4, 0]} barSize={22} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.full} fill={d.full === selected ? colors.selected : colors.other} />
              ))}
            </Bar>
            {baselines.map((b, i) => (
              <ReferenceLine
                key={b.name}
                x={b.mae}
                stroke={colors.ink}
                strokeOpacity={0.7}
                strokeDasharray={DASHES[i % DASHES.length]}
                ifOverflow="extendDomain"
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {baselines.map((b, i) => (
          <li key={b.name} className="flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="22" y2="4" stroke={colors.ink} strokeDasharray={DASHES[i % DASHES.length]} />
            </svg>
            {b.label}: <span className="num text-ink">{fmt(b.mae, digits)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
