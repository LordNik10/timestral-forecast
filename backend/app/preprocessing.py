"""Rilevamento della colonna del tempo e della frequenza, regolarizzazione della serie ed etichette future."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset

from app.errors import DataError
from app.loader import to_numeric_smart

TimeKind = Literal["datetime", "year", "season", "index"]
Aggregation = Literal["sum", "mean"]

KIND_PRIORITY: dict[str, int] = {"datetime": 1, "year": 2, "season": 3, "index": 4}
MIN_VALID_OBS = 8
MAX_MISSING_RATIO = 0.5
MAX_GRID_POINTS = 200_000

SEASON_LENGTH: dict[str, int | None] = {
    "hourly": 24, "daily": 7, "weekly": 52, "monthly": 12, "quarterly": 4,
    "annual": None, "season": None, "index": None, "custom": None,
}
FREQUENCY_LABELS = {
    "hourly": "oraria", "daily": "giornaliera", "weekly": "settimanale", "monthly": "mensile",
    "quarterly": "trimestrale", "annual": "annuale", "season": "stagionale", "index": "indice intero",
    "custom": "regolare",
}
_PERIOD_FREQ = {"hourly": "h", "daily": "D", "monthly": "M", "quarterly": "Q-DEC", "annual": "Y-DEC"}
_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

_SEASON_RE = r"^\s*(\d{4})\s*([-/])\s*(\d{2}|\d{4})\s*$"
_YEAR_RE = re.compile(r"^\d{4}(\.0+)?$")
_NAME_HINTS = ("data", "date", "time", "tempo", "anno", "year", "stagione", "season", "mese", "month",
               "giorno", "day", "periodo", "period", "timestamp", "ds", "ora", "hour", "settimana", "week")
# Formati espliciti, dal più specifico; l'ISO 8601 generico viene provato per primo.
_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y", "%d-%m-%Y %H:%M",
                 "%d.%m.%Y", "%Y/%m/%d", "%Y/%m/%d %H:%M", "%m/%Y", "%Y/%m", "%m/%d/%Y", "%m/%d/%Y %H:%M")
# Timestamp Unix plausibili (2000–2100) in secondi o millisecondi.
_EPOCH_S = (946_684_800, 4_102_444_800)


# --------------------------------------------------------------------------- parsing del tempo


@dataclass
class TimeParse:
    """Colonna del tempo interpretata: chiavi ordinabili riga per riga e come formattarle."""

    kind: TimeKind
    keys: pd.Series  # datetime64 per "datetime", interi per gli altri tipi; NaN/NaT se la riga non è valida
    label_format: str = "%Y-%m-%d"  # solo per "datetime"
    season_sep: str = "-"
    season_short: bool = False


def parse_time(s: pd.Series, strict_index: bool = True) -> TimeParse | None:
    """Interpreta una colonna come tempo, nell'ordine datetime → anno → stagione → indice.

    Con `strict_index` (rilevamento automatico) un indice deve essere intero e strettamente crescente; senza,
    basta che sia intero (colonna scelta dall'utente, magari in formato lungo con più gruppi).
    """
    if s.notna().sum() == 0:
        return None
    return (_parse_year(s) or _parse_season(s) or _parse_datetime(s)
            or _parse_index(s, strict_index))


def _text(s: pd.Series) -> pd.Series:
    return s.dropna().astype("string").str.strip()


def _parse_year(s: pd.Series) -> TimeParse | None:
    if pd.api.types.is_datetime64_any_dtype(s) or pd.api.types.is_bool_dtype(s):
        return None
    if not pd.api.types.is_numeric_dtype(s) and not _text(s).str.match(_YEAR_RE).all():
        return None
    values, ok = to_numeric_smart(s)
    v = values.dropna()
    if ok < 1.0 or v.empty or not np.all(v == np.round(v)) or not v.between(1800, 2100).all():
        return None
    return TimeParse("year", values.round().astype("Int64"))


def _parse_season(s: pd.Series) -> TimeParse | None:
    if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
        return None
    text = s.astype("string").str.strip()
    parts = text.str.extract(_SEASON_RE)
    present = text.notna()
    if parts[0][present].isna().any():
        return None
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[2], errors="coerce")
    short = parts[2][present].str.len() == 2
    expected = np.where(short, (first[present] + 1) % 100, first[present] + 1)
    if not np.array_equal(second[present].to_numpy(dtype=float), expected.astype(float)):
        return None
    sep = parts[1][present].mode().iloc[0]
    return TimeParse("season", first.astype("Int64"), season_sep=str(sep), season_short=bool(short.all()))


def _parse_datetime(s: pd.Series) -> TimeParse | None:
    if pd.api.types.is_datetime64_any_dtype(s):
        keys = _naive(pd.to_datetime(s))
        return TimeParse("datetime", keys, _format_from_values(keys))
    if pd.api.types.is_numeric_dtype(s):
        return _parse_epoch(s)
    present = s.notna()
    text = s.astype("string").str.strip()
    if text[present].str.fullmatch(r"[-+]?\d+(\.\d+)?").all():
        return None  # numeri puri: eventualmente indice o timestamp numerico, non date testuali
    parsed = pd.to_datetime(text, format="ISO8601", errors="coerce")
    if parsed[present].notna().all():
        try:
            keys = _naive(parsed)
        except (TypeError, ValueError):
            keys = None
        if keys is not None:
            return TimeParse("datetime", keys, _iso_format(text[present]))
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        if parsed[present].notna().all():
            return TimeParse("datetime", parsed, fmt)
    return None


def _naive(values: pd.Series) -> pd.Series:
    dt = pd.to_datetime(values, utc=False)
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_localize(None)
    return dt


def _parse_epoch(s: pd.Series) -> TimeParse | None:
    v = s.dropna().astype(float)
    if v.empty or not np.all(v == np.round(v)) or not v.is_monotonic_increasing:
        return None
    lo, hi = _EPOCH_S
    if v.between(lo, hi).all():
        unit = "s"
    elif v.between(lo * 1000, hi * 1000).all():
        unit = "ms"
    else:
        return None
    keys = pd.to_datetime(s.astype(float), unit=unit, errors="coerce")
    return TimeParse("datetime", keys, _format_from_values(keys))


def _parse_index(s: pd.Series, strict: bool) -> TimeParse | None:
    if pd.api.types.is_bool_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
        return None
    values, ok = to_numeric_smart(s)
    v = values.dropna()
    if ok < 1.0 or len(v) < 2 or not np.all(v == np.round(v)):
        return None
    if strict and not (v.is_monotonic_increasing and v.is_unique):
        return None
    return TimeParse("index", values.round().astype("Int64"))


def _iso_format(text: pd.Series) -> str:
    if text.str.fullmatch(r"\d{4}-\d{2}").all():
        return "%Y-%m"
    if text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        return "%Y-%m-%d"
    sep = "T" if text.str.contains("T", regex=False).any() else " "
    if text.str.contains(r"\d{2}:\d{2}:\d{2}").any():
        return f"%Y-%m-%d{sep}%H:%M:%S"
    return f"%Y-%m-%d{sep}%H:%M"


def _format_from_values(keys: pd.Series) -> str:
    k = keys.dropna()
    if k.empty or (k == k.dt.normalize()).all():
        return "%Y-%m-%d"
    if (k.dt.second == 0).all():
        return "%Y-%m-%d %H:%M"
    return "%Y-%m-%d %H:%M:%S"


# --------------------------------------------------------------------------- suggerimenti per l'anteprima


def column_type(s: pd.Series) -> str:
    """Tipo rilevato per l'anteprima: datetime, season, year, integer, float, boolean, text, empty."""
    if s.notna().sum() == 0:
        return "empty"
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    tp = parse_time(s, strict_index=True)
    if tp is not None and tp.kind in ("datetime", "season", "year"):
        return tp.kind
    values, ok = to_numeric_smart(s)
    if ok == 1.0:
        v = values.dropna()
        return "integer" if np.all(v == np.round(v)) else "float"
    return "text"


def suggest_time_column(df: pd.DataFrame) -> str | None:
    best: tuple[int, int, int] | None = None
    best_col: str | None = None
    for i, col in enumerate(df.columns):
        tp = parse_time(df[col], strict_index=True)
        if tp is None:
            continue
        hint = 0 if any(h in col.lower() for h in _NAME_HINTS) else 1
        score = (KIND_PRIORITY[tp.kind], hint, i)
        if best is None or score < best:
            best, best_col = score, col
    return best_col


def suggest_value_column(df: pd.DataFrame, time_col: str | None) -> str | None:
    fallback = None
    for col in df.columns:
        if col == time_col:
            continue
        kind = column_type(df[col])
        if kind in ("integer", "float"):
            return col
        if kind == "year" and fallback is None:
            fallback = col
    return fallback


def suggest_group_column(df: pd.DataFrame, time_col: str | None) -> str | None:
    """Una colonna testuale a bassa cardinalità che rende unico il tempo, se il tempo ha duplicati."""
    if time_col is None or df[time_col].is_unique:
        return None
    for col in df.columns:
        if col == time_col or column_type(df[col]) != "text":
            continue
        n = df[col].nunique()
        if 2 <= n <= 200 and not df.duplicated([time_col, col]).any():
            return col
    return None


# --------------------------------------------------------------------------- frequenza


@dataclass(frozen=True)
class Frequency:
    kind: str  # hourly, daily, weekly, monthly, quarterly, annual, season, index, custom
    period: str | None = None  # frequenza dei pd.Period per i tipi calendariali
    tick: str | None = None  # passo fisso (es. "15min") per le frequenze "custom"
    step: int = 1  # passo intero per anni, stagioni e indici
    anchor: Literal["start", "end"] = "start"

    @property
    def season_length(self) -> int | None:
        return SEASON_LENGTH[self.kind]


def infer_frequency(tp: TimeParse) -> Frequency:
    if tp.kind == "season":
        return Frequency("season")
    if tp.kind == "year":
        return Frequency("annual")
    if tp.kind == "index":
        v = np.unique(tp.keys.dropna().to_numpy(dtype=np.int64))
        step = int(np.gcd.reduce(np.diff(v))) if len(v) > 1 else 1
        return Frequency("index", step=max(step, 1))
    return _datetime_frequency(pd.DatetimeIndex(tp.keys.dropna().unique()).sort_values())


def _datetime_frequency(times: pd.DatetimeIndex) -> Frequency:
    if len(times) < 2:
        raise DataError("Servono almeno due istanti distinti per ricavare la frequenza.")
    inferred = None
    if len(times) >= 3:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # pandas 3 avvisa che restituirà un offset: to_offset gestisce entrambi
                inferred = pd.infer_freq(times)
        except (TypeError, ValueError):
            inferred = None
    if inferred:
        freq = _from_offset(to_offset(inferred), times)
        if freq is not None:
            return freq
    median = pd.Series(times).diff().dropna().median()
    return _from_step(median, times)


def _from_offset(off: pd.DateOffset, times: pd.DatetimeIndex) -> Frequency | None:
    n = getattr(off, "n", 1)
    if isinstance(off, pd.offsets.Week) and n == 1:
        return _weekly(times)
    if isinstance(off, (pd.offsets.MonthBegin, pd.offsets.MonthEnd, pd.offsets.BusinessMonthBegin,
                        pd.offsets.BusinessMonthEnd)) and n == 1:
        return Frequency("monthly", period="M", anchor=_anchor(times, "M"))
    if isinstance(off, (pd.offsets.QuarterBegin, pd.offsets.QuarterEnd)) and n == 1:
        return Frequency("quarterly", period="Q-DEC", anchor=_anchor(times, "Q-DEC"))
    if isinstance(off, (pd.offsets.YearBegin, pd.offsets.YearEnd)) and n == 1:
        return Frequency("annual", period="Y-DEC", anchor=_anchor(times, "Y-DEC"))
    if isinstance(off, pd.offsets.BusinessDay) and n == 1:
        return Frequency("daily", period="D")
    if isinstance(off, pd.offsets.Tick):
        delta = pd.Timedelta(off)
        if delta == pd.Timedelta(hours=1):
            return Frequency("hourly", period="h")
        if delta == pd.Timedelta(days=1):
            return Frequency("daily", period="D")
        if delta == pd.Timedelta(days=7):
            return _weekly(times)
        return Frequency("custom", tick=_tick_string(delta))
    return None


def _from_step(median: pd.Timedelta, times: pd.DatetimeIndex) -> Frequency:
    days = median / pd.Timedelta(days=1)
    hours = median / pd.Timedelta(hours=1)
    if 0.75 <= hours <= 1.5:
        return Frequency("hourly", period="h")
    if 0.75 <= days <= 1.5:
        return Frequency("daily", period="D")
    if 5 <= days <= 9:
        return _weekly(times)
    if 25 <= days <= 35:
        return Frequency("monthly", period="M", anchor=_anchor(times, "M"))
    if 80 <= days <= 100:
        return Frequency("quarterly", period="Q-DEC", anchor=_anchor(times, "Q-DEC"))
    if 340 <= days <= 390:
        return Frequency("annual", period="Y-DEC", anchor=_anchor(times, "Y-DEC"))
    if median <= pd.Timedelta(0):
        raise DataError("Impossibile ricavare la frequenza: gli istanti non sono distinti.")
    return Frequency("custom", tick=_tick_string(median.round("min") if median >= pd.Timedelta(minutes=1)
                                                 else median.round("s")))


def _weekly(times: pd.DatetimeIndex) -> Frequency:
    # Il periodo settimanale termina il giorno prima del giorno della settimana dei dati, così inizia su quello.
    weekday = int(pd.Series(times.day_of_week).mode().iloc[0])
    return Frequency("weekly", period=f"W-{_WEEKDAYS[(weekday - 1) % 7]}")


def _anchor(times: pd.DatetimeIndex, period: str) -> Literal["start", "end"]:
    ends = times.to_period(period).to_timestamp(how="end").normalize()
    return "end" if (times.normalize() == ends).all() else "start"


def _tick_string(delta: pd.Timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        raise DataError("Impossibile ricavare la frequenza: passo temporale nullo.")
    if seconds % 86400 == 0:
        return f"{seconds // 86400}D"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    return f"{seconds}s"


# --------------------------------------------------------------------------- serie regolare


@dataclass
class PreparedSeries:
    labels: list[str]
    y: np.ndarray
    frequency: Frequency
    time_kind: TimeKind
    warnings: list[str] = field(default_factory=list)
    _parse: TimeParse | None = None
    _last_key: object = None

    @property
    def n_obs(self) -> int:
        return len(self.y)

    @property
    def n_missing(self) -> int:
        return int(np.isnan(self.y).sum())

    @property
    def season_length(self) -> int | None:
        return self.frequency.season_length

    def future_labels(self, h: int) -> list[str]:
        assert self._parse is not None
        keys = _advance(self._last_key, self.frequency, h)
        return [_format_key(k, self._parse, self.frequency) for k in keys]


def prepare_series(
    df: pd.DataFrame,
    time_col: str,
    value_col: str,
    group_col: str | None = None,
    group_value: str | None = None,
    aggregation: Aggregation = "sum",
) -> PreparedSeries:
    """Filtra il gruppo, ordina per tempo, aggrega i duplicati e porta la serie su una griglia regolare.

    I buchi della griglia restano NaN: Timestral li tratta come valori mancanti, quindi non si interpola.
    """
    for col in (time_col, value_col, group_col):
        if col is not None and col not in df.columns:
            raise DataError(f"La colonna «{col}» non esiste nel file.")
    if time_col == value_col:
        raise DataError("La colonna del tempo e quella del valore devono essere diverse.")
    if aggregation not in ("sum", "mean"):
        raise DataError("Aggregazione non valida: usa «somma» o «media».")

    tp = parse_time(df[time_col], strict_index=False)
    if tp is None:
        raise DataError(f"La colonna «{time_col}» non è interpretabile come tempo: servono date, anni, "
                        "stagioni (es. 2016-2017) o un indice intero ordinabile.")

    values, ok = to_numeric_smart(df[value_col])
    if df[value_col].notna().sum() == 0 or ok < 0.9:
        raise DataError(f"La colonna «{value_col}» non contiene valori numerici: scegli un'altra colonna "
                        "da prevedere.")

    mask = pd.Series(True, index=df.index)
    if group_col is not None:
        if group_value is None:
            raise DataError(f"Scegli quale gruppo di «{group_col}» analizzare.")
        mask = df[group_col].astype("string").str.strip() == str(group_value).strip()
        if not mask.any():
            raise DataError(f"Il gruppo «{group_value}» non è presente nella colonna «{group_col}».")

    warnings: list[str] = []
    keys = tp.keys[mask]
    vals = values[mask]
    bad_time = keys.isna() & df.loc[mask, time_col].notna()
    if bad_time.any():
        warnings.append(f"{int(bad_time.sum())} righe con tempo non interpretabile sono state ignorate.")
    keep = keys.notna()
    keys, vals = keys[keep], vals[keep]
    if keys.empty:
        raise DataError(f"La colonna «{time_col}» non contiene istanti validi.")

    freq = infer_frequency(TimeParse(tp.kind, keys, tp.label_format, tp.season_sep, tp.season_short))
    grid_keys = _grid_keys(keys, freq)
    frame = pd.DataFrame({"k": grid_keys.to_numpy(), "v": vals.to_numpy(dtype=float)})
    if frame["k"].duplicated().any():
        n_dup = int(frame["k"].duplicated().sum())
        warnings.append(f"{n_dup} righe cadevano su istanti già presenti e sono state aggregate "
                        f"({'somma' if aggregation == 'sum' else 'media'}).")
    grouped = frame.groupby("k", sort=True)["v"]
    agg = grouped.sum(min_count=1) if aggregation == "sum" else grouped.mean()

    full = _full_grid(agg.index, freq)
    if len(full) > MAX_GRID_POINTS:
        raise DataError(f"La griglia temporale avrebbe {len(full):,} punti: la frequenza rilevata non è adatta "
                        "a questi dati.".replace(",", "."))
    series = agg.reindex(full)
    y = series.to_numpy(dtype=float)
    n_valid = int(np.isfinite(y).sum())
    if n_valid < MIN_VALID_OBS:
        raise DataError(f"La serie ha solo {n_valid} osservazioni valide: ne servono almeno {MIN_VALID_OBS}.")
    missing_ratio = 1 - n_valid / len(y)
    if missing_ratio > MAX_MISSING_RATIO:
        raise DataError(f"Troppi valori mancanti: {missing_ratio:.0%} della griglia regolare è vuoto "
                        "(massimo 50%).".replace(".", ","))

    labels = [_format_key(k, tp, freq) for k in full]
    if len(y) < 30:
        warnings.append("Serie corta (meno di 30 punti): interpretare le metriche con cautela.")
    if np.isnan(y).any():
        warnings.append(f"{int(np.isnan(y).sum())} istanti mancanti nella griglia regolare: restano vuoti "
                        "e il modello li tratta come mancanti, senza interpolazione.")
    return PreparedSeries(labels, y, freq, tp.kind, warnings, tp, full[-1])


def _grid_keys(keys: pd.Series, freq: Frequency) -> pd.Index:
    if freq.period is not None:
        return pd.PeriodIndex(pd.DatetimeIndex(keys).to_period(freq.period))
    if freq.tick is not None:
        return pd.DatetimeIndex(keys).floor(freq.tick)
    return pd.Index(keys.astype("int64"))


def _full_grid(index: pd.Index, freq: Frequency) -> pd.Index:
    lo, hi = index.min(), index.max()
    if freq.period is not None:
        return pd.period_range(lo, hi, freq=freq.period)
    if freq.tick is not None:
        return pd.date_range(lo, hi, freq=freq.tick)
    n = (int(hi) - int(lo)) // freq.step + 1
    if n > MAX_GRID_POINTS:
        return pd.RangeIndex(0, n)  # solo per far scattare il controllo sulla dimensione
    return pd.Index(range(int(lo), int(hi) + 1, freq.step), dtype="int64")


def _advance(last: object, freq: Frequency, h: int) -> list[object]:
    if freq.period is not None:
        return [last + i for i in range(1, h + 1)]  # type: ignore[operator]
    if freq.tick is not None:
        step = pd.Timedelta(freq.tick)
        return [last + i * step for i in range(1, h + 1)]  # type: ignore[operator]
    return [int(last) + i * freq.step for i in range(1, h + 1)]  # type: ignore[call-overload]


def _format_key(key: object, tp: TimeParse, freq: Frequency) -> str:
    if tp.kind == "season":
        y = int(key)  # type: ignore[call-overload]
        end = f"{(y + 1) % 100:02d}" if tp.season_short else str(y + 1)
        return f"{y}{tp.season_sep}{end}"
    if tp.kind in ("year", "index"):
        return str(int(key))  # type: ignore[call-overload]
    if isinstance(key, pd.Period):
        ts = key.to_timestamp(how=freq.anchor)
        ts = ts.normalize() if freq.anchor == "end" else ts
    else:
        ts = pd.Timestamp(key)  # type: ignore[arg-type]
    return ts.strftime(tp.label_format)


def default_horizon(frequency: str) -> int:
    return {"hourly": 24, "daily": 14, "weekly": 13, "monthly": 12, "quarterly": 4}.get(frequency, 3)
