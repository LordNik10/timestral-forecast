"""Metriche di accuratezza. Tutte ignorano i punti in cui il valore reale manca (NaN)."""

from __future__ import annotations

import numpy as np


def _valid(y: np.ndarray, *others: np.ndarray) -> np.ndarray:
    mask = np.isfinite(y)
    for o in others:
        mask &= np.isfinite(o)
    return mask


def mae(y: np.ndarray, yhat: np.ndarray) -> float:
    m = _valid(y, yhat)
    return float(np.mean(np.abs(y[m] - yhat[m]))) if m.any() else float("nan")


def rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    m = _valid(y, yhat)
    return float(np.sqrt(np.mean((y[m] - yhat[m]) ** 2))) if m.any() else float("nan")


def smape(y: np.ndarray, yhat: np.ndarray) -> float:
    """sMAPE in percentuale (0–200), ignorando i punti con denominatore nullo."""
    m = _valid(y, yhat)
    denom = np.abs(y[m]) + np.abs(yhat[m])
    nz = denom > 0
    if not nz.any():
        return float("nan")
    return float(np.mean(2 * np.abs(y[m] - yhat[m])[nz] / denom[nz]) * 100)


def naive_scale(context: np.ndarray, lag: int = 1) -> float:
    """Errore medio assoluto del naive (stagionale se lag > 1) in-sample sul contesto; NaN se non calcolabile."""
    if len(context) <= lag:
        return float("nan")
    diffs = np.abs(context[lag:] - context[:-lag])
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size == 0:
        return float("nan")
    scale = float(diffs.mean())
    return scale if scale > 0 else float("nan")


def mase(y: np.ndarray, yhat: np.ndarray, scales: np.ndarray) -> float:
    """MASE su finestre `(W, H)`: ogni errore è diviso per la scala naive in-sample della sua finestra `(W,)`."""
    scaled = np.abs(y - yhat) / scales[:, None]
    m = np.isfinite(scaled)
    return float(np.mean(scaled[m])) if m.any() else float("nan")


def interval_coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    m = _valid(y, lo, hi)
    return float(np.mean((y[m] >= lo[m]) & (y[m] <= hi[m]))) if m.any() else float("nan")


def interval_width(lo: np.ndarray, hi: np.ndarray) -> float:
    m = _valid(lo, hi)
    return float(np.mean(hi[m] - lo[m])) if m.any() else float("nan")


def wql(y: np.ndarray, quantiles: np.ndarray, levels: tuple[float, ...] | np.ndarray) -> float:
    """Weighted quantile loss media sui livelli: `mean_q [2 Σ pinball_q] / Σ |y|`.

    `y` ha forma `(...)`, `quantiles` `(..., Q)`.
    """
    m = np.isfinite(y)
    if not m.any():
        return float("nan")
    yy = y[m][:, None]
    qq = quantiles[m]
    lv = np.asarray(levels, dtype=float)[None, :]
    diff = yy - qq
    pinball = np.maximum(lv * diff, (lv - 1) * diff)
    denom = np.abs(yy).sum()
    if denom == 0:
        return float("nan")
    return float(np.mean(2 * pinball.sum(axis=0) / denom))


def point_metrics(y: np.ndarray, yhat: np.ndarray, scales: np.ndarray) -> dict[str, float]:
    return {"mae": mae(y, yhat), "rmse": rmse(y, yhat), "smape": smape(y, yhat), "mase": mase(y, yhat, scales)}
