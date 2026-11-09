import type { ForecastRequest, InspectResponse, JobResponse, ModelsResponse } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

/** Traduce le risposte d'errore di FastAPI (stringa o lista di validazione) in un messaggio leggibile. */
function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationIssue[])
        .map((d) => {
          const field = d.loc?.filter((p) => p !== "body").join(".");
          const msg = (d.msg ?? "valore non valido").replace(/^Value error, /, "");
          return field ? `${field}: ${msg}` : msg;
        })
        .join("; ");
    }
  }
  if (status === 413) return "Il file supera il limite di 50 MB.";
  return `Errore del server (${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `Impossibile contattare il backend su ${API_URL}. Verifica che sia avviato (make dev).`,
      0,
    );
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status);
  return body as T;
}

export function getModels(): Promise<ModelsResponse> {
  return request<ModelsResponse>("/api/models");
}

export function inspectFile(file: File): Promise<InspectResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<InspectResponse>("/api/inspect", { method: "POST", body: form });
}

export function inspectGroups(fileId: string, groupCol: string): Promise<InspectResponse> {
  const form = new FormData();
  form.append("file_id", fileId);
  form.append("group_col", groupCol);
  return request<InspectResponse>("/api/inspect", { method: "POST", body: form });
}

export function startForecast(req: ForecastRequest): Promise<{ job_id: string }> {
  return request<{ job_id: string }>("/api/forecast", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export function getJob(jobId: string): Promise<JobResponse> {
  return request<JobResponse>(`/api/jobs/${jobId}`);
}

/** Interroga il job finché termina; `onUpdate` riceve ogni stato intermedio. */
export async function waitForJob(
  jobId: string,
  onUpdate: (job: JobResponse) => void,
  signal?: AbortSignal,
): Promise<JobResponse> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Annullato", "AbortError");
    const job = await getJob(jobId);
    onUpdate(job);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((r) => setTimeout(r, 600));
  }
}
