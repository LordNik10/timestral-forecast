"""Registro delle taglie di Timestral, cache dei modelli caricati e adapter verso l'interfaccia del backtest."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

import numpy as np

from app.backtest import ForecastContext

log = logging.getLogger(__name__)

SIZES: dict[str, int] = {"5M": 21, "28M": 111, "123M": 490, "209M": 837}  # peso approssimativo in MB
DEFAULT_SIZES = ("5M", "28M")
REPO_PREFIX = "mistralai/Timestral-"
WEIGHTS_FILE = "model.safetensors"
# Le serie da almeno tanti punti raggruppano le origini del backtest in un'unica chiamata (vedi test_models_slow).
BATCH_MIN_LENGTH = 30
BATCH_SIZE = 16


def model_name(size: str) -> str:
    return f"Timestral-{size}"


def repo_id(size: str) -> str:
    return f"{REPO_PREFIX}{size}"


def size_from_name(name: str) -> str:
    size = name.removeprefix("Timestral-")
    if size not in SIZES:
        raise KeyError(name)
    return size


def select_device() -> str:
    import torch

    forced = os.environ.get("TIMESTRAL_DEVICE")
    if forced:
        return forced
    return "cuda" if torch.cuda.is_available() else "cpu"


def offline_mode() -> bool:
    return os.environ.get("TIMESTRAL_OFFLINE", "") == "1" or os.environ.get("HF_HUB_OFFLINE", "") == "1"


def is_cached(size: str) -> bool:
    """Vero se i pesi sono già nella cache di Hugging Face (nessun download necessario)."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    path = try_to_load_from_cache(repo_id(size), WEIGHTS_FILE)
    return isinstance(path, str) and os.path.exists(path)


def timestral_available() -> bool:
    try:
        import timestral  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class TimestralModel:
    """Adapter con l'interfaccia `QuantileModel` del backtest. L'inferenza è serializzata da un lock per modello."""

    name: str
    forecaster: object
    lock: threading.Lock
    batch: bool = True

    @property
    def quantile_levels(self) -> tuple[float, ...]:
        return tuple(float(q) for q in self.forecaster.quantile_levels)  # type: ignore[attr-defined]

    def predict(self, contexts: list[ForecastContext], horizon: int) -> np.ndarray:
        if not contexts:
            return np.empty((0, horizon, len(self.quantile_levels)))
        longest = max(len(c.target) for c in contexts)
        if self.batch and len(contexts) > 1 and longest >= BATCH_MIN_LENGTH:
            parts = [self._predict_batch(contexts[i: i + BATCH_SIZE], horizon)
                     for i in range(0, len(contexts), BATCH_SIZE)]
            return np.concatenate(parts)
        return np.stack([self._predict_one(c, horizon) for c in contexts])

    def _forecast(self, context, horizon, past=None, known=None) -> np.ndarray:
        with self.lock:
            fc = self.forecaster.forecast(  # type: ignore[attr-defined]
                context, prediction_length=horizon, past_covariates=past, known_covariates=known
            )
            return fc.quantiles.cpu().numpy()

    def _predict_one(self, c: ForecastContext, horizon: int) -> np.ndarray:
        past = c.past_covariates[None] if c.past_covariates is not None else None
        known = c.known_covariates[None] if c.known_covariates is not None else None
        return self._forecast(c.target.astype(np.float32), horizon, past, known)[0, 0]

    def _predict_batch(self, contexts: list[ForecastContext], horizon: int) -> np.ndarray:
        """Contesti allineati a destra con NaN a sinistra: Timestral li tratta come mancanti."""
        t = max(len(c.target) for c in contexts)
        ctx = np.stack([_left_pad(c.target, t) for c in contexts]).astype(np.float32)
        past = known = None
        if contexts[0].past_covariates is not None:
            past = np.stack([_left_pad(c.past_covariates, t) for c in contexts])  # type: ignore[arg-type]
        if contexts[0].known_covariates is not None:
            known = np.stack([_left_pad(c.known_covariates, t + horizon) for c in contexts])  # type: ignore[arg-type]
        return self._forecast(ctx, horizon, past, known)[:, 0]


def _left_pad(x: np.ndarray, length: int) -> np.ndarray:
    pad = length - x.shape[-1]
    if pad <= 0:
        return x
    widths = [(0, 0)] * (x.ndim - 1) + [(pad, 0)]
    return np.pad(x.astype(np.float32), widths, constant_values=np.nan)


class ModelRegistry:
    """Cache dei modelli già caricati, condivisa da tutti i job."""

    def __init__(self, device: str | None = None):
        self._device = device
        self._models: dict[str, TimestralModel] = {}
        self._load_lock = threading.Lock()

    @property
    def device(self) -> str:
        if self._device is None:
            self._device = select_device()
        return self._device

    def loaded(self) -> list[str]:
        return list(self._models)

    def get(self, size: str) -> TimestralModel:
        if size not in SIZES:
            raise KeyError(size)
        with self._load_lock:
            if size not in self._models:
                from timestral import TimestralForecaster

                local_only = offline_mode() or is_cached(size)
                log.info("Carico %s su %s (solo cache locale: %s)", repo_id(size), self.device, local_only)
                forecaster = TimestralForecaster.from_pretrained(
                    repo_id(size), device=self.device, local_files_only=local_only
                )
                self._models[size] = TimestralModel(model_name(size), forecaster, threading.Lock())
            return self._models[size]
