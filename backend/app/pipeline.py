"""Job di forecast: preprocessing, backtest e previsione futura per ogni taglia richiesta."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app import backtest as bt
from app.backtest import SeriesInput
from app.errors import DataError
from app.models import SIZES, ModelRegistry, is_cached, model_name, offline_mode
from app.preprocessing import FREQUENCY_LABELS, Aggregation, prepare_series

MAX_HORIZON = 1000

Reporter = Callable[[str, float, str | None], None]


@dataclass
class ForecastParams:
    time_col: str
    value_col: str
    models: list[str]  # taglie, es. ["5M", "28M"]
    horizon: int
    backtest_windows: int = bt.DEFAULT_WINDOWS
    aggregation: Aggregation = "sum"
    group_col: str | None = None
    group_value: str | None = None


class ModelLoadError(DataError):
    """Il modello non si carica: pesi assenti offline, rete assente o pacchetto mancante."""


def _load_error_message(name: str, size: str, e: Exception) -> str:
    if isinstance(e, ImportError):
        return "Il pacchetto timestral non è installato nel backend: vedi il README (make setup)."
    if offline_mode():
        return (f"I pesi di {name} non sono nella cache locale e la modalità offline è attiva: "
                "scegli una taglia già scaricata o disattiva TIMESTRAL_OFFLINE.")
    return (f"Impossibile scaricare i pesi di {name} (~{SIZES[size]} MB) da Hugging Face: verifica la "
            "connessione oppure scegli una taglia già in cache.")


def num(x: float | np.floating | None) -> float | None:
    """Float JSON-safe a 7 cifre significative; None per NaN e infiniti."""
    if x is None:
        return None
    x = float(x)
    if not np.isfinite(x):
        return None
    return float(f"{x:.7g}")


def run_forecast(df: pd.DataFrame, params: ForecastParams, registry: ModelRegistry, report: Reporter,
                 file_name: str | None = None) -> dict:
    report("preprocessing", 0.02, "Preparazione della serie")
    series = prepare_series(df, params.time_col, params.value_col, params.group_col, params.group_value,
                            params.aggregation)
    y = series.y
    m = series.season_length
    plan = bt.plan_backtest(series.n_obs, params.horizon, params.backtest_windows)
    baselines, k = bt.baseline_backtest(y, plan, m)
    truth = bt.targets(y, plan)
    future_labels = series.future_labels(params.horizon)
    warnings = list(series.warnings)
    if plan.reduced_horizon:
        warnings.append(f"Orizzonte troppo lungo per la serie: il backtest usa {plan.horizon} passi per finestra.")
    if plan.windows < plan.requested_windows:
        warnings.append(f"Richieste {plan.requested_windows} finestre di backtest, ne entrano {plan.windows}.")
    if "seasonal_naive" not in baselines and m:
        warnings.append("Storia troppo corta per la baseline stagionale (servono due cicli completi).")

    models_out: dict[str, dict] = {}
    n_models = len(params.models)
    levels: tuple[float, ...] = ()
    for i, size in enumerate(params.models):
        name = model_name(size)

        def at(fraction: float, _i: int = i) -> float:
            return 0.05 + 0.95 * (_i + fraction) / n_models

        if is_cached(size):
            report("loading_model", at(0), f"Caricamento di {name}")
        else:
            report("loading_model", at(0), f"Download dei pesi di {name} (~{SIZES[size]} MB) da Hugging Face: "
                                            "al primo uso può richiedere alcuni minuti")
        try:
            model = registry.get(size)
        except (OSError, ConnectionError, ImportError) as e:
            raise ModelLoadError(_load_error_message(name, size, e)) from e
        levels = model.quantile_levels
        report("backtest", at(0.2), f"Backtest di {name} su {plan.windows} finestre")
        q_bt = bt.model_backtest(model, SeriesInput(y), plan)
        evaluation = bt.evaluate(y, plan, q_bt, levels, baselines, m)
        report("forecast", at(0.8), f"Previsione futura con {name}")
        q_future = model.predict([SeriesInput(y).context(len(y), params.horizon)], params.horizon)[0]
        models_out[name] = {
            "backtest": _backtest_rows(series.labels, plan, truth, q_bt, levels, baselines),
            "metrics": {"model": {k_: num(v) for k_, v in evaluation.model.items()},
                        **{b: {k_: num(v) for k_, v in mm.items()} for b, mm in evaluation.baselines.items()}},
            "forecast": _forecast_rows(future_labels, q_future, levels),
            "summary": bt.summary_sentence(name, evaluation, k),
        }

    report("done", 1.0, None)
    return {
        "meta": {
            "time_col": params.time_col,
            "value_col": params.value_col,
            "group_col": params.group_col,
            "group": params.group_value if params.group_col else None,
            "aggregation": params.aggregation,
            "frequency": series.frequency.kind,
            "frequency_label": FREQUENCY_LABELS[series.frequency.kind],
            "time_kind": series.time_kind,
            "season_length": m,
            "n_obs": series.n_obs,
            "n_missing": series.n_missing,
            "horizon": params.horizon,
            "backtest_horizon": plan.horizon,
            "backtest_windows": plan.windows,
            "requested_windows": plan.requested_windows,
            "mean_k": k,
            "file_name": file_name,
            "warnings": warnings,
            "quantile_levels": list(levels),
            "device": registry.device,
        },
        "history": [{"t": t, "y": num(v)} for t, v in zip(series.labels, y)],
        "baselines": list(baselines),
        "baseline_labels": {b: bt.baseline_label(b, k) for b in baselines},
        "models": models_out,
    }


def _backtest_rows(labels, plan, truth, q, levels, baselines) -> list[dict]:
    i10, i50, i90 = (bt.quantile_index(levels, p) for p in (0.1, 0.5, 0.9))
    rows = []
    for w, origin in enumerate(plan.origins):
        for s in range(plan.horizon):
            row = {"origin": labels[origin - 1], "t": labels[origin + s], "step": s + 1, "y": num(truth[w, s]),
                   "p10": num(q[w, s, i10]), "p50": num(q[w, s, i50]), "p90": num(q[w, s, i90])}
            row.update({b: num(pred[w, s]) for b, pred in baselines.items()})
            rows.append(row)
    return rows


def _forecast_rows(labels, q, levels) -> list[dict]:
    i10, i50, i90 = (bt.quantile_index(levels, p) for p in (0.1, 0.5, 0.9))
    return [{"t": t, "p10": num(q[s, i10]), "p50": num(q[s, i50]), "p90": num(q[s, i90]),
             "quantiles": [num(v) for v in q[s]]} for s, t in enumerate(labels)]
