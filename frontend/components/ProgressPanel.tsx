"use client";

import { STAGE_LABELS } from "@/lib/format";
import type { JobResponse } from "@/lib/types";
import { Card, Skeleton, cx } from "./ui";

const STAGES = ["preprocessing", "loading_model", "backtest", "forecast"] as const;

export function ProgressPanel({ job, title = "Elaborazione in corso" }: { job: JobResponse | null; title?: string }) {
  const stage = job?.stage ?? "queued";
  const current = STAGES.indexOf(stage as (typeof STAGES)[number]);
  const progress = Math.max(0.02, job?.progress ?? 0);
  const downloading = stage === "loading_model" && /download/i.test(job?.message ?? "");

  return (
    <Card title={title} aside={`${Math.round(progress * 100)}%`}>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${progress * 100}%` }} />
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-4">
        {STAGES.map((s, i) => (
          <li
            key={s}
            className={cx(
              "rounded-lg border px-3 py-2 text-sm",
              i === current ? "border-accent text-ink" : i < current ? "border-line text-muted" : "border-line text-muted/60",
            )}
          >
            <span className="mr-1.5">{i < current ? "✓" : i === current ? "●" : "○"}</span>
            {STAGE_LABELS[s]}
          </li>
        ))}
      </ol>
      <p className={cx("mt-3 min-h-5 text-sm", downloading ? "font-medium text-warn" : "text-muted")} aria-live="polite">
        {job?.message ?? (stage === "queued" ? "In attesa di avvio…" : "")}
      </p>
    </Card>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-xl border border-line bg-surface p-4">
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="mt-3 h-8 w-2/3" />
            <Skeleton className="mt-2 h-3 w-1/3" />
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-line bg-surface p-4">
        <Skeleton className="h-4 w-1/4" />
        <Skeleton className="mt-4 h-72 w-full" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  );
}
