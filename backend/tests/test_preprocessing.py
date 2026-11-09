import io
import json

import numpy as np
import pandas as pd
import pytest

from app.errors import DataError
from app.loader import read_table, to_numeric_smart
from app.preprocessing import (
    column_type,
    parse_time,
    prepare_series,
    suggest_group_column,
    suggest_time_column,
    suggest_value_column,
)
from tests.conftest import read_sample


def frame(**cols) -> pd.DataFrame:
    return pd.DataFrame(cols)


def strings(values) -> pd.Series:
    return pd.Series(values, dtype="string")


# --------------------------------------------------------------------------- lettura file


def test_read_csv_semicolon_decimal_comma_cp1252():
    text = "Data;Quantità\n01/01/2024;1.234,5\n02/01/2024;7,25\n"
    df = read_table("dati.csv", text.encode("cp1252"))
    assert list(df.columns) == ["Data", "Quantità"]
    values, ok = to_numeric_smart(df["Quantità"])
    assert ok == 1.0
    assert values.tolist() == [1234.5, 7.25]


def test_read_tsv_json_xlsx():
    tsv = read_table("x.tsv", b"t\tv\n1\t2\n2\t3\n")
    assert list(tsv.columns) == ["t", "v"]
    js = read_table("x.json", json.dumps([{"t": "2024-01", "v": 1}, {"t": "2024-02", "v": 2}]).encode())
    assert js["v"].tolist() == [1, 2]
    buf = io.BytesIO()
    pd.DataFrame({"data": pd.date_range("2024-01-01", periods=3), "v": [1.0, 2.0, 3.0]}).to_excel(buf, index=False)
    xl = read_table("x.xlsx", buf.getvalue())
    assert column_type(xl["data"]) == "datetime"


def test_read_rejects_bad_json_and_empty():
    with pytest.raises(DataError):
        read_table("x.json", b'{"a": 1}')
    with pytest.raises(DataError):
        read_table("x.csv", b"   ")


# --------------------------------------------------------------------------- rilevamento del tempo


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        (["2024-01-01", "2024-01-02", "2024-01-03"], "datetime"),
        (["01/02/2024", "02/02/2024", "15/02/2024"], "datetime"),
        (["2024-01", "2024-02", "2024-03"], "datetime"),
        (["2016-2017", "2017-2018", "2018-2019"], "season"),
        (["2016/17", "2017/18", "2099/00"], "season"),
        (["1999", "2000", "2001"], "year"),
        (["1", "2", "3", "10"], "index"),
    ],
)
def test_parse_time_kinds(values, kind):
    tp = parse_time(strings(values))
    assert tp is not None and tp.kind == kind


def test_season_requires_consecutive_years():
    assert parse_time(strings(["2016-2018", "2017-2019"])) is None or \
        parse_time(strings(["2016-2018", "2017-2019"])).kind != "season"


def test_numeric_epoch_timestamps():
    tp = parse_time(pd.Series([1_700_000_000, 1_700_003_600, 1_700_007_200]))
    assert tp is not None and tp.kind == "datetime"


def test_suggestions_on_gol():
    df = read_table("gol.csv", read_sample("gol_stagionali.csv"))
    assert suggest_time_column(df) == "Stagione_Anno"
    assert suggest_value_column(df, "Stagione_Anno") == "Presenze"
    assert column_type(df["Stagione_Anno"]) == "season"
    assert column_type(df["Squadra"]) == "text"
    assert column_type(df["Gol"]) == "integer"
    assert suggest_group_column(df, "Stagione_Anno") is None


def test_datetime_beats_index_and_year():
    df = frame(n=["1", "2", "3"], anno=["2020", "2021", "2022"], quando=["2020-01-01", "2020-01-02", "2020-01-03"])
    df = df.astype("string")
    assert suggest_time_column(df) == "quando"


def test_suggest_group_column_long_format():
    df = read_table("s.csv", read_sample("sensore_orario.csv"))
    assert suggest_time_column(df) == "timestamp"
    assert suggest_group_column(df, "timestamp") == "sensore"
    assert suggest_value_column(df, "timestamp") == "temperatura"


# --------------------------------------------------------------------------- frequenza e stagionalità


def test_gol_season_series():
    df = read_table("gol.csv", read_sample("gol_stagionali.csv"))
    s = prepare_series(df, "Stagione_Anno", "Gol")
    assert s.frequency.kind == "season"
    assert s.season_length is None
    assert s.n_obs == 10 and s.n_missing == 0
    assert s.y.tolist() == [9, 18, 9, 21, 19, 25, 28, 27, 22, 23]
    assert s.labels[0] == "2016-2017"
    assert s.future_labels(3) == ["2026-2027", "2027-2028", "2028-2029"]


def test_short_season_labels():
    df = frame(s=["2097/98", "2098/99"] + [f"{y}/{(y + 1) % 100:02d}" for y in range(2099, 2106)], v=list(range(9)))
    s = prepare_series(df.astype({"s": "string"}), "s", "v")
    assert s.labels[2] == "2099/00"
    assert s.future_labels(2) == ["2106/07", "2107/08"]


def test_monthly_sample():
    df = read_table("v.csv", read_sample("vendite_mensili.csv"))
    s = prepare_series(df, "Mese", "Vendite")
    assert s.frequency.kind == "monthly"
    assert s.season_length == 12
    assert s.n_obs == 96
    assert s.labels[-1] == "2024-12"
    assert s.future_labels(3) == ["2025-01", "2025-02", "2025-03"]


@pytest.mark.parametrize(
    ("dates", "kind", "season", "future"),
    [
        (pd.date_range("2024-01-01", periods=40, freq="D"), "daily", 7, "2024-02-10"),
        (pd.date_range("2024-01-01", periods=40, freq="W-MON"), "weekly", 52, "2024-10-07"),
        (pd.date_range("2020-01-31", periods=40, freq="ME"), "monthly", 12, "2023-05-31"),
        (pd.date_range("2020-01-01", periods=40, freq="QS"), "quarterly", 4, "2030-01-01"),
        (pd.date_range("1990-01-01", periods=40, freq="YS"), "annual", None, "2030-01-01"),
    ],
)
def test_datetime_frequencies(dates, kind, season, future):
    df = frame(t=dates.strftime("%Y-%m-%d"), v=np.arange(40.0))
    s = prepare_series(df.astype({"t": "string"}), "t", "v")
    assert s.frequency.kind == kind
    assert s.season_length == season
    assert s.future_labels(1) == [future]


def test_hourly_frequency_and_labels():
    df = frame(t=pd.date_range("2024-03-01 00:00", periods=48, freq="h").strftime("%Y-%m-%d %H:%M"),
               v=np.arange(48.0))
    s = prepare_series(df.astype({"t": "string"}), "t", "v")
    assert s.frequency.kind == "hourly" and s.season_length == 24
    assert s.future_labels(2) == ["2024-03-03 00:00", "2024-03-03 01:00"]


def test_irregular_monthly_dates_use_median_step():
    dates = ["2024-01-03", "2024-02-05", "2024-03-02", "2024-04-07", "2024-05-01",
             "2024-06-04", "2024-07-03", "2024-08-06", "2024-09-02"]
    s = prepare_series(frame(t=dates, v=np.arange(9.0)).astype({"t": "string"}), "t", "v")
    assert s.frequency.kind == "monthly"
    assert s.n_obs == 9


def test_years_and_index():
    years = prepare_series(frame(a=list(range(2000, 2010)), v=np.arange(10.0)), "a", "v")
    assert years.frequency.kind == "annual" and years.future_labels(2) == ["2010", "2011"]
    idx = prepare_series(frame(i=list(range(1, 11)), v=np.arange(10.0)), "i", "v")
    assert idx.frequency.kind == "index" and idx.future_labels(1) == ["11"]


# --------------------------------------------------------------------------- regolarizzazione


def test_gaps_stay_missing():
    dates = pd.date_range("2024-01-01", periods=20, freq="D").delete([5, 6, 12])
    df = frame(t=dates.strftime("%Y-%m-%d"), v=np.arange(17.0))
    s = prepare_series(df.astype({"t": "string"}), "t", "v")
    assert s.n_obs == 20 and s.n_missing == 3
    assert np.isnan(s.y[[5, 6, 12]]).all()
    assert s.y[4] == 4 and s.y[7] == 5


def test_sensor_groups_keep_gaps():
    df = read_table("s.csv", read_sample("sensore_orario.csv"))
    a = prepare_series(df, "timestamp", "temperatura", "sensore", "sensore_a")
    b = prepare_series(df, "timestamp", "temperatura", "sensore", "sensore_b")
    assert a.frequency.kind == "hourly"
    assert a.n_obs <= 1440 and a.n_missing >= 25
    assert np.isnan(a.y[700:706]).all()
    assert not np.array_equal(np.nan_to_num(a.y), np.nan_to_num(b.y[: len(a.y)]))


def test_duplicates_sum_or_mean():
    df = frame(t=["2024", "2024", "2025"] + [str(y) for y in range(2026, 2033)], v=[1.0, 3.0] + [5.0] * 8)
    df = df.astype({"t": "string"})
    assert prepare_series(df, "t", "v").y[0] == 4.0
    assert prepare_series(df, "t", "v", aggregation="mean").y[0] == 2.0


def test_unsorted_input_is_sorted():
    df = frame(t=[str(y) for y in (2005, 2001, 2003, 2002, 2004, 2000, 2007, 2006)], v=np.arange(8.0))
    s = prepare_series(df.astype({"t": "string"}), "t", "v")
    assert s.labels[0] == "2000" and s.y[0] == 5.0


# --------------------------------------------------------------------------- validazione


def test_too_few_observations():
    df = read_table("c.csv", read_sample("troppo_corto.csv"))
    with pytest.raises(DataError, match="almeno 8"):
        prepare_series(df, "data", "valore")


def test_text_value_column():
    df = read_table("gol.csv", read_sample("gol_stagionali.csv"))
    with pytest.raises(DataError, match="non contiene valori numerici"):
        prepare_series(df, "Stagione_Anno", "Squadra")


def test_unsortable_time():
    df = frame(t=["alfa", "beta"] * 5, v=np.arange(10.0)).astype({"t": "string"})
    with pytest.raises(DataError, match="non è interpretabile come tempo"):
        prepare_series(df, "t", "v")


def test_too_many_missing():
    years = [2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2030]
    with pytest.raises(DataError, match="Troppi valori mancanti"):
        prepare_series(frame(a=years, v=np.arange(9.0)), "a", "v")


def test_missing_group_value():
    df = read_table("s.csv", read_sample("sensore_orario.csv"))
    with pytest.raises(DataError):
        prepare_series(df, "timestamp", "temperatura", "sensore", "sensore_z")
