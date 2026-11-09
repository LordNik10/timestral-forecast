"""Stato in memoria: file caricati e job, entrambi con scadenza. Nessun database."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import pandas as pd

TTL_SECONDS = 3600

T = TypeVar("T")


class TTLStore(Generic[T]):
    def __init__(self, ttl: float = TTL_SECONDS):
        self.ttl = ttl
        self._items: dict[str, tuple[float, T]] = {}
        self._lock = threading.Lock()

    def put(self, value: T) -> str:
        key = uuid.uuid4().hex
        with self._lock:
            self._purge()
            self._items[key] = (time.monotonic(), value)
        return key

    def get(self, key: str) -> T | None:
        with self._lock:
            self._purge()
            item = self._items.get(key)
            if item is None:
                return None
            self._items[key] = (time.monotonic(), item[1])  # l'uso rinnova la scadenza
            return item[1]

    def __len__(self) -> int:
        with self._lock:
            self._purge()
            return len(self._items)

    def _purge(self) -> None:
        now = time.monotonic()
        for k in [k for k, (ts, _) in self._items.items() if now - ts > self.ttl]:
            del self._items[k]


@dataclass
class UploadedFile:
    name: str
    frame: pd.DataFrame


@dataclass
class Job:
    status: str = "queued"  # queued | running | done | error
    stage: str = "queued"
    progress: float = 0.0
    message: str | None = None
    result: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **fields: Any) -> None:
        with self.lock:
            for k, v in fields.items():
                setattr(self, k, v)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            out: dict[str, Any] = {"status": self.status, "stage": self.stage,
                                   "progress": round(self.progress, 4), "message": self.message}
            if self.result is not None:
                out["result"] = self.result
            return out
