"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getModels, inspectFile, startForecast, waitForJob } from "@/lib/api";
import { downloadForecastCsv, downloadSession, parseSession } from "@/lib/exporters";
import type {
  ForecastRequest,
  ForecastResult,
  GroupValue,
  InspectResponse,
  JobResponse,
  ModelInfo,
} from "@/lib/types";
import { Dashboard } from "./Dashboard";
import { MappingStep } from "./MappingStep";
import { DashboardSkeleton, ProgressPanel } from "./ProgressPanel";
import { ThemeToggle } from "./ThemeToggle";
import { UploadStep } from "./UploadStep";
import { ErrorBox } from "./ui";

type Step = "upload" | "mapping" | "running" | "dashboard";

interface Analysis {
  fileName: string;
  request: ForecastRequest;
  groupValues: GroupValue[] | null;
  result: ForecastResult;
  fromSavedFile: boolean;
}

/** Taglia mostrata di default: la più grande tra quelle elaborate. */
function defaultModel(result: ForecastResult): string {
  const names = Object.keys(result.models);
  return names[names.length - 1];
}

export function App() {
  const [step, setStep] = useState<Step>("upload");
  const [uploading, setUploading] = useState(false);
  const [inspect, setInspect] = useState<InspectResponse | null>(null);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [rerun, setRerun] = useState<JobResponse | null | undefined>(undefined);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ForecastRequest | null>(null);
  const abort = useRef<AbortController | null>(null);

  const refreshModels = useCallback(() => {
    getModels()
      .then((r) => setModels(r.models))
      .catch(() => setModels(null));
  }, []);

  useEffect(() => {
    refreshModels();
    return () => abort.current?.abort();
  }, [refreshModels]);

  async function execute(req: ForecastRequest, onUpdate: (j: JobResponse) => void): Promise<ForecastResult> {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const { job_id } = await startForecast(req);
    const final = await waitForJob(job_id, onUpdate, controller.signal);
    if (final.status === "error" || !final.result) {
      throw new Error(final.message ?? "L'elaborazione non è andata a buon fine.");
    }
    return final.result;
  }

  async function onFile(file: File) {
    setError(null);
    setUploading(true);
    try {
      const r = await inspectFile(file);
      setInspect(r);
      setDraft(null);
      setStep("mapping");
      refreshModels();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function onSession(file: File) {
    setError(null);
    try {
      const s = parseSession(await file.text());
      setAnalysis({
        fileName: s.file_name,
        request: s.request,
        groupValues: s.group_values,
        result: s.result,
        fromSavedFile: true,
      });
      setSelected(defaultModel(s.result));
      setStep("dashboard");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function onSubmit(req: ForecastRequest, groupValues: GroupValue[] | null) {
    if (!inspect) return;
    setError(null);
    setJob(null);
    setDraft(req);
    setStep("running");
    try {
      const result = await execute(req, setJob);
      setAnalysis({ fileName: inspect.file_name, request: req, groupValues, result, fromSavedFile: false });
      setSelected(defaultModel(result));
      setStep("dashboard");
      refreshModels();
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError((e as Error).message);
      setStep("mapping");
    }
  }

  /** Ricalcolo dalla dashboard: nuova taglia (si aggiunge alle altre) o nuovo gruppo (sostituisce tutto). */
  async function rerunFromDashboard(req: ForecastRequest, mode: "add-model" | "replace") {
    if (!analysis) return;
    setError(null);
    setRerun(null);
    try {
      const result = await execute(req, setRerun);
      const merged: ForecastResult =
        mode === "add-model"
          ? { ...analysis.result, models: sortModels({ ...analysis.result.models, ...result.models }) }
          : result;
      const models = mode === "add-model" ? Object.keys(merged.models) : req.models;
      setAnalysis({
        ...analysis,
        request: { ...req, models },
        result: merged,
      });
      if (mode === "add-model") setSelected(req.models[0]);
      refreshModels();
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setRerun(undefined);
    }
  }

  function onSelectModel(name: string) {
    if (!analysis) return;
    if (name in analysis.result.models) {
      setSelected(name);
      return;
    }
    void rerunFromDashboard({ ...analysis.request, models: [name] }, "add-model");
  }

  function onSelectGroup(value: string) {
    if (!analysis || value === analysis.result.meta.group) return;
    const models = Object.keys(analysis.result.models);
    void rerunFromDashboard({ ...analysis.request, group_value: value, models }, "replace");
  }

  function reset() {
    abort.current?.abort();
    setStep("upload");
    setInspect(null);
    setDraft(null);
    setAnalysis(null);
    setJob(null);
    setRerun(undefined);
    setError(null);
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-5 sm:px-6 lg:py-8">
      <nav className="mb-6 flex items-center justify-between gap-3">
        <button type="button" onClick={reset} className="text-left">
          <span className="num text-xl text-ink">Previsioni</span>
          <span className="ml-2 text-sm text-muted">con Timestral, in locale</span>
        </button>
        <ThemeToggle />
      </nav>

      {error && step !== "dashboard" && (
        <div className="mb-4">
          <ErrorBox message={error} onClose={() => setError(null)} />
        </div>
      )}

      {step === "upload" && <UploadStep busy={uploading} onFile={onFile} onSession={onSession} />}

      {step === "mapping" && inspect && (
        <MappingStep inspect={inspect} models={models} initial={draft} onSubmit={onSubmit} onBack={reset} />
      )}

      {step === "running" && (
        <div className="space-y-4">
          <ProgressPanel job={job} />
          <DashboardSkeleton />
        </div>
      )}

      {step === "dashboard" && analysis && (
        <Dashboard
          result={analysis.result}
          fileName={analysis.fileName}
          selected={selected}
          onSelectModel={onSelectModel}
          groupValues={analysis.groupValues}
          onSelectGroup={onSelectGroup}
          onNewDataset={reset}
          onDownloadJson={() =>
            downloadSession(analysis.fileName, analysis.request, analysis.groupValues, analysis.result)
          }
          onDownloadCsv={() => downloadForecastCsv(analysis.fileName, analysis.result)}
          busyJob={rerun}
          error={error}
          onDismissError={() => setError(null)}
          models={models}
          fromSavedFile={analysis.fromSavedFile}
        />
      )}
    </div>
  );
}

const ORDER = ["Timestral-5M", "Timestral-28M", "Timestral-123M", "Timestral-209M"];

function sortModels<T>(models: Record<string, T>): Record<string, T> {
  return Object.fromEntries(Object.entries(models).sort(([a], [b]) => ORDER.indexOf(a) - ORDER.indexOf(b)));
}
