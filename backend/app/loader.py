"""Lettura di file tabellari (CSV, TSV, XLSX, JSON) in un DataFrame e rilevamento dei tipi di colonna."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import PurePath

import numpy as np
import pandas as pd

from app.errors import DataError

MAX_FILE_BYTES = 50 * 1024 * 1024
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
DELIMITERS = (",", ";", "\t", "|")

_DECIMAL_COMMA_RE = re.compile(r"^[-+]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    """Legge il file in un DataFrame. I file di testo vengono letti come stringhe; i tipi si deducono dopo."""
    if len(content) > MAX_FILE_BYTES:
        raise DataError("Il file supera il limite di 50 MB.")
    if not content.strip():
        raise DataError("Il file è vuoto.")
    ext = PurePath(filename or "").suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        df = _read_excel(content)
    elif ext == ".xls":
        raise DataError("Il formato .xls non è supportato: salva il file come .xlsx o .csv.")
    elif ext == ".json":
        df = _read_json(content)
    else:
        df = _read_delimited(content, prefer_tab=ext == ".tsv")
    df = _clean_frame(df)
    if df.shape[1] == 0 or df.shape[0] == 0:
        raise DataError("Il file non contiene righe o colonne leggibili.")
    return df


def decode_text(content: bytes) -> str:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16")
    for enc in ENCODINGS:
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DataError("Impossibile riconoscere la codifica del file.")


def sniff_delimiter(text: str, prefer_tab: bool = False) -> str:
    lines = [ln for ln in text.splitlines()[:50] if ln.strip()]
    if not lines:
        raise DataError("Il file è vuoto.")
    if prefer_tab and "\t" in lines[0]:
        return "\t"
    sample = "\n".join(lines)
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(DELIMITERS)).delimiter
    except csv.Error:
        pass
    # Ripiego: il separatore presente nell'intestazione con il conteggio più stabile tra le righe.
    best, best_score = ",", -1.0
    for d in DELIMITERS:
        counts = [ln.count(d) for ln in lines]
        if counts[0] == 0:
            continue
        stable = sum(c == counts[0] for c in counts) / len(counts)
        score = stable * 10 + counts[0]
        if score > best_score:
            best, best_score = d, score
    return best


def _read_delimited(content: bytes, prefer_tab: bool) -> pd.DataFrame:
    text = decode_text(content)
    sep = sniff_delimiter(text, prefer_tab)
    try:
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, skipinitialspace=True, engine="python")
    except (pd.errors.ParserError, ValueError) as e:
        raise DataError(f"Impossibile leggere il file come tabella delimitata da '{_sep_name(sep)}'.") from e


def _sep_name(sep: str) -> str:
    return {"\t": "tabulazione", ",": "virgola", ";": "punto e virgola", "|": "barra verticale"}.get(sep, sep)


def _read_excel(content: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception as e:  # openpyxl solleva eccezioni eterogenee sui file corrotti
        raise DataError("Impossibile leggere il file Excel: verifica che sia un .xlsx valido.") from e


def _read_json(content: bytes) -> pd.DataFrame:
    try:
        data = json.loads(decode_text(content))
    except json.JSONDecodeError as e:
        raise DataError("Il file JSON non è valido.") from e
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            data = lists[0]
    if not isinstance(data, list) or not data or not all(isinstance(r, dict) for r in data):
        raise DataError("Il JSON deve essere un array di oggetti, uno per riga.")
    return pd.DataFrame.from_records(data)


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() or f"colonna_{i + 1}" for i, c in enumerate(df.columns)]
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed: \d+$") | df.notna().any().to_numpy()]
    for c in df.columns:
        if _is_textual(df[c]):
            s = df[c].astype("string").str.strip()
            df[c] = s.mask(s == "")
    return df.dropna(how="all").reset_index(drop=True)


def _is_textual(s: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def to_numeric_smart(s: pd.Series) -> tuple[pd.Series, float]:
    """Converte in numeri, accettando anche la virgola decimale italiana. Restituisce (valori, quota convertita)."""
    present = s.notna()
    n = int(present.sum())
    if pd.api.types.is_bool_dtype(s):
        return s.astype(float), 1.0 if n else 0.0
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float), 1.0 if n else 0.0
    if n == 0:
        return pd.Series(np.nan, index=s.index, dtype=float), 0.0
    text = s.astype("string").str.strip()
    values = pd.to_numeric(text, errors="coerce")
    ok = float(values[present].notna().mean())
    if ok < 1.0:
        comma = text[present & values.isna()].dropna()
        if len(comma) and comma.str.match(_DECIMAL_COMMA_RE).all():
            alt = pd.to_numeric(text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                                errors="coerce")
            alt_ok = float(alt[present].notna().mean())
            if alt_ok > ok:
                values, ok = alt, alt_ok
    return values.astype(float), ok


def json_safe(value: object) -> object:
    """Valore adatto all'anteprima JSON: stringhe per date e oggetti, None per i mancanti."""
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ") if (value.hour or value.minute or value.second) else value.date().isoformat()
    return str(value)
