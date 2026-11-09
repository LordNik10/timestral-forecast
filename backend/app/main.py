"""API FastAPI del forecasting locale con Timestral. Stato solo in memoria."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from app import backtest as bt
from app.errors import DataError
from app.jobs import Job, TTLStore, UploadedFile
from app.loader import MAX_FILE_BYTES, json_safe, read_table
from app.models import (
    DEFAULT_SIZES,
    SIZES,
    ModelRegistry,
    is_cached,
    model_name,
    offline_mode,
    repo_id,
    timestral_available,
)
from app.pipeline import MAX_HORIZON, ForecastParams, run_forecast
from app.preprocessing import (
    TimeParse,
    column_type,
    default_horizon,
    infer_frequency,
    parse_time,
    suggest_group_column,
    suggest_time_column,
    suggest_value_column,
)

log = logging.getLogger("timestral_app")
PREVIEW_ROWS = 20
MAX_GROUP_VALUES = 500


class ForecastRequest(BaseModel):
    file_id: str
    time_col: str
    value_col: str
    group_col: str | None = None
    group_value: str | None = None
    aggregation: Literal["sum", "mean"] = "sum"
    models: list[str] = Field(default_factory=lambda: [model_name(s) for s in DEFAULT_SIZES], min_length=1)
    horizon: int = Field(default=3, ge=1, le=MAX_HORIZON)
    backtest_windows: int = Field(default=bt.DEFAULT_WINDOWS, ge=1, le=bt.MAX_WINDOWS)

    @field_validator("models")
    @classmethod
    def known_models(cls, v: list[str]) -> list[str]:
        sizes = []
        for name in v:
            size = name.removeprefix("Timestral-")
            if size not in SIZES:
                raise ValueError(f"Taglia sconosciuta: {name}. Disponibili: {', '.join(SIZES)}.")
            if size not in sizes:
                sizes.append(size)
        return sorted(sizes, key=list(SIZES).index)


def create_app(registry: ModelRegistry | None = None, workers: int = 2) -> FastAPI:
    app = FastAPI(title="Timestral Forecast (locale)", version="0.1.0")
    origins = [o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

    reg = registry or ModelRegistry()
    files: TTLStore[UploadedFile] = TTLStore()
    jobs: TTLStore[Job] = TTLStore()
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="forecast")
    app.state.registry, app.state.files, app.state.jobs = reg, files, jobs

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "device": reg.device, "timestral_installed": timestral_available(),
                "offline": offline_mode(), "loaded_models": [model_name(s) for s in reg.loaded()]}

    @app.get("/api/models")
    def models() -> dict:
        loaded = set(reg.loaded())
        return {
            "device": reg.device,
            "models": [{"name": model_name(s), "size": s, "repo": repo_id(s), "weight_mb": mb,
                        "cached": is_cached(s), "loaded": s in loaded, "default": s in DEFAULT_SIZES}
                       for s, mb in SIZES.items()],
        }

    @app.post("/api/inspect")
    async def inspect(
        file: Annotated[UploadFile | None, File()] = None,
        file_id: Annotated[str | None, Form()] = None,
        group_col: Annotated[str | None, Form()] = None,
    ) -> dict:
        if file is not None:
            content = await file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise HTTPException(413, "Il file supera il limite di 50 MB.")
            try:
                frame = read_table(file.filename or "", content)
            except DataError as e:
                raise HTTPException(400, str(e)) from e
            uploaded = UploadedFile(file.filename or "dati", frame)
            file_id = files.put(uploaded)
        elif file_id:
            uploaded = files.get(file_id)  # type: ignore[assignment]
            if uploaded is None:
                raise HTTPException(404, "Il file non è più in memoria (scade dopo un'ora): caricalo di nuovo.")
        else:
            raise HTTPException(400, "Carica un file oppure indica un file_id.")
        return _describe(file_id, uploaded, group_col or None)

    @app.post("/api/forecast")
    def forecast(req: ForecastRequest) -> dict:
        uploaded = files.get(req.file_id)
        if uploaded is None:
            raise HTTPException(404, "Il file non è più in memoria (scade dopo un'ora): caricalo di nuovo.")
        for col in (req.time_col, req.value_col, req.group_col):
            if col is not None and col not in uploaded.frame.columns:
                raise HTTPException(400, f"La colonna «{col}» non esiste nel file.")
        params = ForecastParams(req.time_col, req.value_col, req.models, req.horizon, req.backtest_windows,
                                req.aggregation, req.group_col or None, req.group_value)
        job = Job()
        job_id = jobs.put(job)
        executor.submit(_run_job, job, uploaded, params, reg)
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job inesistente o scaduto.")
        return job.snapshot()

    return app


def _run_job(job: Job, uploaded: UploadedFile, params: ForecastParams, reg: ModelRegistry) -> None:
    def report(stage: str, progress: float, message: str | None) -> None:
        job.update(status="running", stage=stage, progress=progress, message=message)

    job.update(status="running", stage="preprocessing")
    try:
        result = run_forecast(uploaded.frame, params, reg, report, uploaded.name)
    except DataError as e:
        job.update(status="error", stage="error", message=str(e))
    except Exception as e:  # nessuno stack trace verso l'utente: va nel log del server
        log.exception("Job di forecast fallito")
        job.update(status="error", stage="error",
                   message=f"Errore inatteso durante l'elaborazione ({type(e).__name__}). Dettagli nel log del backend.")
    else:
        job.update(status="done", stage="done", progress=1.0, message=None, result=result)


def _detected_frequency(df, time_col: str | None, group_col: str | None) -> str | None:
    """Frequenza della colonna del tempo suggerita, sul primo gruppo se il file è in formato lungo."""
    if time_col is None:
        return None
    tp = parse_time(df[time_col])
    if tp is None:
        return None
    if group_col is not None:
        first = df[group_col].dropna().iloc[0]
        tp = TimeParse(tp.kind, tp.keys[df[group_col] == first], tp.label_format)
    try:
        return infer_frequency(tp).kind
    except DataError:
        return None


def _describe(file_id: str, uploaded: UploadedFile, group_col: str | None) -> dict:
    df = uploaded.frame
    if group_col is not None and group_col not in df.columns:
        raise HTTPException(400, f"La colonna «{group_col}» non esiste nel file.")
    time_col = suggest_time_column(df)
    columns = [{"name": c, "type": column_type(df[c]), "n_missing": int(df[c].isna().sum()),
                "n_unique": int(df[c].nunique())} for c in df.columns]
    preview = [{c: json_safe(v) for c, v in row.items()} for row in df.head(PREVIEW_ROWS).to_dict("records")]
    suggested_group = suggest_group_column(df, time_col)
    frequency = _detected_frequency(df, time_col, suggested_group)
    out = {
        "file_id": file_id,
        "file_name": uploaded.name,
        "n_rows": len(df),
        "columns": columns,
        "preview": preview,
        "suggested_time_col": time_col,
        "suggested_value_col": suggest_value_column(df, time_col),
        "suggested_group_col": suggested_group,
        "detected_frequency": frequency,
        "suggested_horizon": default_horizon(frequency) if frequency else 3,
        "group_col": group_col,
        "group_values": None,
    }
    if group_col is not None:
        counts = df[group_col].dropna().astype("string").str.strip().value_counts()
        values = sorted(counts.index.tolist(), key=lambda v: (-int(counts[v]), v))[:MAX_GROUP_VALUES]
        out["group_values"] = [{"value": v, "count": int(counts[v])} for v in values]
    return out


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
