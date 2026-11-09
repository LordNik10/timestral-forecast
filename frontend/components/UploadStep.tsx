"use client";

import { useRef, useState, type DragEvent } from "react";
import { MAX_UPLOAD_BYTES } from "@/lib/api";
import { Button, Card, Skeleton, cx } from "./ui";

const ACCEPT = ".csv,.tsv,.txt,.xlsx,.xlsm,.json";

export function UploadStep({
  busy,
  onFile,
  onSession,
}: {
  busy: boolean;
  onFile: (file: File) => void;
  onSession: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const sessionInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  function pick(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setLocalError("Il file supera il limite di 50 MB.");
      return;
    }
    setLocalError(null);
    onFile(file);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  }

  if (busy) {
    return (
      <Card title="Lettura del file">
        <div className="space-y-3" aria-busy>
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2" title="1 · Carica un dataset">
        <div
          role="button"
          tabIndex={0}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "flex min-h-52 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center transition",
            dragging ? "border-accent bg-surface-2" : "border-line hover:border-accent/60",
          )}
        >
          <p className="num text-2xl text-ink">Trascina qui il file</p>
          <p className="text-sm text-muted">oppure fai clic per sceglierlo</p>
          <p className="mt-2 text-xs text-muted">CSV, TSV, XLSX o JSON (array di oggetti) · massimo 50 MB</p>
        </div>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {localError && <p className="mt-3 text-sm text-bad">{localError}</p>}
      </Card>
      <Card title="Hai già un risultato?">
        <p className="text-sm text-muted">
          Ricarica il JSON scaricato da una dashboard precedente per rivederla senza ricalcolare nulla.
        </p>
        <Button className="mt-4 w-full" onClick={() => sessionInput.current?.click()}>
          Apri un risultato salvato
        </Button>
        <input
          ref={sessionInput}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onSession(f);
            e.target.value = "";
          }}
        />
        <div className="mt-6 border-t border-line pt-4 text-xs text-muted">
          <p className="font-medium text-ink">Dataset di esempio</p>
          <p className="mt-1">
            Nella cartella <code>samples/</code>: <code>gol_stagionali.csv</code>, <code>vendite_mensili.csv</code>,{" "}
            <code>sensore_orario.csv</code>.
          </p>
        </div>
      </Card>
    </div>
  );
}
