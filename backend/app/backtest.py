"""Backtest rolling origin, baseline e valutazione dei modelli quantilici.

Il modello vede solo oggetti `ForecastContext`: oggi portano solo il target, ma hanno già i campi per le
covariate di Timestral (`past_covariates`, `known_covariates`), che `SeriesInput.context` taglia per ogni
origine. Aggiungere le covariate non richiede quindi di toccare il backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app import metrics

SHORT_SERIES = 30
MAX_WINDOWS = 50
DEFAULT_WINDOWS = 10

BASELINE_LABELS = {"naive": "Naive (ultimo valore)", "mean_k": "Media ultime {k}", "seasonal_naive": "Stagionale naive"}
_SUMMARY_LABELS = {"naive": "naive", "mean_k": "media delle ultime {k}", "seasonal_naive": "naive stagionale"}


@dataclass
class ForecastContext:
    """Quello che il modello vede a un'origine: il passato del target e le eventuali covariate."""

    target: np.ndarray  # (T,)
    past_covariates: np.ndarray | None = None  # (C, T)
    known_covariates: np.ndarray | None = None  # (C, T + orizzonte)


@dataclass
class SeriesInput:
    y: np.ndarray  # (N,) con NaN per i mancanti
    past_covariates: np.ndarray | None = None  # (C, N)
    known_covariates: np.ndarray | None = None  # (C, N + orizzonte futuro)

    def context(self, end: int, horizon: int) -> ForecastContext:
        """Contesto per prevedere `y[end:end + horizon]` usando solo `y[:end]`."""
        past = self.past_covariates[:, :end] if self.past_covariates is not None else None
        known = self.known_covariates[:, : end + horizon] if self.known_covariates is not None else None
        return ForecastContext(self.y[:end], past, known)


class QuantileModel(Protocol):
    quantile_levels: tuple[float, ...]

    def predict(self, contexts: list[ForecastContext], horizon: int) -> np.ndarray:
        """Quantili `(len(contexts), horizon, Q)`."""
        ...


# --------------------------------------------------------------------------- finestre


@dataclass(frozen=True)
class BacktestPlan:
    horizon: int  # passi previsti per finestra (h_bt)
    origins: tuple[int, ...]  # indici di fine contesto, dal più vecchio al più recente
    min_context: int
    requested_windows: int
    reduced_horizon: bool = False

    @property
    def windows(self) -> int:
        return len(self.origins)


def plan_backtest(n: int, horizon: int, requested_windows: int = DEFAULT_WINDOWS) -> BacktestPlan:
    """Finestre non sovrapposte che terminano sull'ultima osservazione.

    `h_bt` è l'orizzonte scelto, ma 1 per serie sotto i 30 punti; ogni finestra lascia almeno
    `max(4, 2·h_bt)` punti di contesto.
    """
    requested = int(min(max(requested_windows, 1), MAX_WINDOWS))
    h = 1 if n < SHORT_SERIES else max(1, horizon)
    reduced = False
    if n - max(4, 2 * h) < h:
        h, reduced = max(1, n // 3), True  # orizzonte troppo lungo per la serie: lo si riduce per il backtest
    min_ctx = max(4, 2 * h)
    fit = max(0, (n - min_ctx) // h)
    w = min(requested, fit)
    origins = tuple(n - k * h for k in range(w, 0, -1))
    return BacktestPlan(h, origins, min_ctx, requested, reduced)


def targets(y: np.ndarray, plan: BacktestPlan) -> np.ndarray:
    return np.stack([y[o: o + plan.horizon] for o in plan.origins]) if plan.origins else np.empty((0, plan.horizon))


# --------------------------------------------------------------------------- baseline


def mean_k_window(n: int, season_length: int | None) -> int:
    if n < SHORT_SERIES:
        return 3
    return season_length or 7


def seasonal_naive_enabled(plan: BacktestPlan, season_length: int | None) -> bool:
    """Serve un periodo stagionale e almeno due cicli di storia anche alla prima origine."""
    return bool(season_length) and bool(plan.origins) and plan.origins[0] >= 2 * season_length  # type: ignore[operator]


def _observed(context: np.ndarray) -> np.ndarray:
    return context[np.isfinite(context)]


def naive_forecast(context: np.ndarray, h: int) -> np.ndarray:
    obs = _observed(context)
    return np.full(h, obs[-1] if obs.size else np.nan)


def mean_k_forecast(context: np.ndarray, h: int, k: int) -> np.ndarray:
    obs = _observed(context)
    return np.full(h, obs[-k:].mean() if obs.size else np.nan)


def seasonal_naive_forecast(context: np.ndarray, h: int, m: int) -> np.ndarray:
    t = len(context)
    out = np.empty(h)
    fallback = naive_forecast(context, 1)[0]
    for s in range(1, h + 1):
        idx = t + s - 1 - m * int(np.ceil(s / m))
        v = context[idx] if 0 <= idx < t else np.nan
        out[s - 1] = v if np.isfinite(v) else fallback
    return out


def baseline_backtest(y: np.ndarray, plan: BacktestPlan, season_length: int | None) -> tuple[dict[str, np.ndarray], int]:
    """Previsioni delle baseline per ogni finestra: `{nome: (W, h_bt)}` e il k della media mobile."""
    k = mean_k_window(len(y), season_length)
    out: dict[str, list[np.ndarray]] = {"naive": [], "mean_k": []}
    seasonal = seasonal_naive_enabled(plan, season_length)
    if seasonal:
        out["seasonal_naive"] = []
    for o in plan.origins:
        ctx = y[:o]
        out["naive"].append(naive_forecast(ctx, plan.horizon))
        out["mean_k"].append(mean_k_forecast(ctx, plan.horizon, k))
        if seasonal:
            out["seasonal_naive"].append(seasonal_naive_forecast(ctx, plan.horizon, season_length))  # type: ignore[arg-type]
    return {name: np.stack(v) if v else np.empty((0, plan.horizon)) for name, v in out.items()}, k


def baseline_label(name: str, k: int) -> str:
    return BASELINE_LABELS[name].format(k=k)


# --------------------------------------------------------------------------- modello


def model_backtest(model: QuantileModel, series: SeriesInput, plan: BacktestPlan) -> np.ndarray:
    """Quantili del modello per ogni finestra: `(W, h_bt, Q)`."""
    contexts = [series.context(o, plan.horizon) for o in plan.origins]
    if not contexts:
        return np.empty((0, plan.horizon, len(model.quantile_levels)))
    return model.predict(contexts, plan.horizon)


def quantile_index(levels: tuple[float, ...] | np.ndarray, level: float) -> int:
    """Indice del livello più vicino: mai un confronto esatto tra float."""
    return int(np.argmin(np.abs(np.asarray(levels, dtype=float) - level)))


def mase_scales(y: np.ndarray, plan: BacktestPlan, lag: int) -> np.ndarray:
    return np.array([metrics.naive_scale(y[:o], lag) for o in plan.origins])


@dataclass
class Evaluation:
    model: dict[str, float]
    baselines: dict[str, dict[str, float]]


def evaluate(
    y: np.ndarray,
    plan: BacktestPlan,
    model_q: np.ndarray,
    levels: tuple[float, ...],
    baselines: dict[str, np.ndarray],
    season_length: int | None,
) -> Evaluation:
    """Metriche aggregate su tutte le finestre e i passi, per il modello (mediana) e per ogni baseline.

    La MASE è scalata sull'errore naive in-sample del contesto di ogni finestra, stagionale se la baseline
    stagionale è attiva.
    """
    truth = targets(y, plan)
    lag = season_length if "seasonal_naive" in baselines and season_length else 1
    scales = mase_scales(y, plan, lag)
    p10 = model_q[..., quantile_index(levels, 0.1)]
    p50 = model_q[..., quantile_index(levels, 0.5)]
    p90 = model_q[..., quantile_index(levels, 0.9)]
    model_metrics = metrics.point_metrics(truth, p50, scales)
    model_metrics.update({
        "coverage_80": metrics.interval_coverage(truth, p10, p90),
        "width_80": metrics.interval_width(p10, p90),
        "wql": metrics.wql(truth, model_q, levels),
    })
    base = {name: metrics.point_metrics(truth, pred, scales) for name, pred in baselines.items()}
    return Evaluation(model_metrics, base)


def best_baseline(evaluation: Evaluation) -> tuple[str, float]:
    finite = {k: v["mae"] for k, v in evaluation.baselines.items() if np.isfinite(v["mae"])}
    if not finite:
        return "", float("nan")
    name = min(finite, key=finite.__getitem__)
    return name, finite[name]


def _fmt(x: float, decimals: int = 2) -> str:
    return f"{x:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def summary_sentence(model_name: str, evaluation: Evaluation, k: int) -> str:
    name, base_mae = best_baseline(evaluation)
    mae = evaluation.model["mae"]
    if not name or not np.isfinite(mae):
        return f"Con {model_name} non è stato possibile confrontare il modello con le baseline."
    label = _SUMMARY_LABELS[name].format(k=k)
    if base_mae == 0:
        delta = ""
    else:
        pct = abs(mae - base_mae) / base_mae * 100
        delta = f" ({_fmt(pct, 1)}% {'in meno' if mae < base_mae else 'in più'})"
    verb = "batte" if mae < base_mae else "non batte"
    return (f"Con {model_name} il modello {verb} la baseline migliore ({label}): errore medio "
            f"{_fmt(mae)} contro {_fmt(base_mae)}{delta}.")
