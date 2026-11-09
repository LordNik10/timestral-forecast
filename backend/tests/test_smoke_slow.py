"""Smoke test end-to-end via API con Timestral-5M reale (marker `slow`)."""

import io
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import timestral_available
from tests.conftest import read_sample

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not timestral_available(), reason="pacchetto timestral non installato"),
]


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def run(client, name, content, request, timeout=300):
    body = client.post("/api/inspect", files={"file": (name, content)}).json()
    r = client.post("/api/forecast", json={"file_id": body["file_id"], **request})
    job_id = r.json()["job_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            assert job["status"] == "done", job["message"]
            return job["result"]
        time.sleep(0.2)
    raise AssertionError("timeout")


def test_gol_end_to_end(client):
    res = run(client, "gol_stagionali.csv", read_sample("gol_stagionali.csv"),
              {"time_col": "Stagione_Anno", "value_col": "Gol", "models": ["Timestral-5M"], "horizon": 3,
               "backtest_windows": 6})
    m = res["models"]["Timestral-5M"]
    assert m["metrics"]["model"]["mae"] == pytest.approx(4.251, abs=0.01)
    assert m["metrics"]["naive"]["mae"] == pytest.approx(3.0, abs=0.01)
    assert m["metrics"]["mean_k"]["mae"] == pytest.approx(4.722, abs=0.01)
    fc = m["forecast"]
    assert [f["t"] for f in fc] == ["2026-2027", "2027-2028", "2028-2029"]
    for f in fc:
        assert f["p10"] <= f["p50"] <= f["p90"]
        assert f["quantiles"] == sorted(f["quantiles"])
        assert f["p10"] >= 0  # contesto non negativo: clip_nonnegative attivo


def test_synthetic_end_to_end(client):
    rng = np.random.default_rng(1)
    days = pd.date_range("2023-01-01", periods=200, freq="D")
    y = 100 + 20 * np.sin(2 * np.pi * np.arange(200) / 7) + rng.normal(0, 2, 200)
    csv = pd.DataFrame({"giorno": days.strftime("%d/%m/%Y"), "visite": np.round(y, 2)}).to_csv(index=False, sep=";")
    res = run(client, "visite.csv", csv.encode(), {"time_col": "giorno", "value_col": "visite",
                                                    "models": ["Timestral-5M"], "horizon": 14})
    assert res["meta"]["frequency"] == "daily" and res["meta"]["season_length"] == 7
    assert res["models"]["Timestral-5M"]["forecast"][0]["t"] == "20/07/2023"
    metrics = res["models"]["Timestral-5M"]["metrics"]
    assert metrics["model"]["mae"] < metrics["naive"]["mae"]
    assert "seasonal_naive" in res["baselines"]


def test_excel_upload(client):
    buf = io.BytesIO()
    pd.DataFrame({"mese": pd.date_range("2020-01-01", periods=36, freq="MS"),
                  "valore": np.arange(36.0) + 10}).to_excel(buf, index=False)
    res = run(client, "serie.xlsx", buf.getvalue(), {"time_col": "mese", "value_col": "valore",
                                                     "models": ["Timestral-5M"], "horizon": 6})
    assert res["meta"]["frequency"] == "monthly"
    assert res["models"]["Timestral-5M"]["forecast"][0]["t"] == "2023-01-01"
