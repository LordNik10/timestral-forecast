import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import read_sample

LEVELS = (0.01, *[round(0.05 * i, 2) for i in range(1, 20)], 0.99)  # i 21 livelli di Timestral


class FakeModel:
    """Ultimo valore osservato con quantili simmetrici: abbastanza per verificare l'API senza Timestral."""

    def __init__(self, name):
        self.name = name
        self.quantile_levels = LEVELS

    def predict(self, contexts, horizon):
        last = np.array([c.target[np.isfinite(c.target)][-1] for c in contexts])
        offsets = (np.array(LEVELS) - 0.5) * 10
        q = last[:, None] + offsets[None, :]
        return np.repeat(q[:, None, :], horizon, axis=1)


class FakeRegistry:
    device = "cpu"

    def __init__(self):
        self.calls = []

    def loaded(self):
        return []

    def get(self, size):
        self.calls.append(size)
        return FakeModel(f"Timestral-{size}")


@pytest.fixture
def client():
    return TestClient(create_app(FakeRegistry()))


def upload(client, name, content=None, **form):
    files = {"file": (name, content if content is not None else read_sample(name))}
    return client.post("/api/inspect", files=files, data=form)


def wait_job(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("job non terminato")


def test_assert_levels_shape():
    assert len(LEVELS) == 21 and 0.5 in LEVELS


def test_health_and_models(client):
    assert client.get("/api/health").json()["status"] == "ok"
    models = client.get("/api/models").json()["models"]
    assert [m["name"] for m in models] == ["Timestral-5M", "Timestral-28M", "Timestral-123M", "Timestral-209M"]
    assert [m["default"] for m in models] == [True, True, False, False]


def test_inspect_gol(client):
    r = upload(client, "gol_stagionali.csv")
    assert r.status_code == 200
    body = r.json()
    assert body["suggested_time_col"] == "Stagione_Anno"
    assert body["suggested_value_col"] == "Presenze"
    assert body["detected_frequency"] == "season" and body["suggested_horizon"] == 3
    assert len(body["preview"]) == 10
    types = {c["name"]: c["type"] for c in body["columns"]}
    assert types["Stagione_Anno"] == "season" and types["Squadra"] == "text" and types["Gol"] == "integer"


def test_inspect_group_values_by_file_id(client):
    file_id = upload(client, "sensore_orario.csv").json()["file_id"]
    r = client.post("/api/inspect", data={"file_id": file_id, "group_col": "sensore"})
    body = r.json()
    assert body["suggested_group_col"] == "sensore"
    assert body["detected_frequency"] == "hourly"
    assert [g["value"] for g in body["group_values"]] == ["sensore_a", "sensore_b"]


def test_inspect_errors(client):
    assert upload(client, "x.json", b'{"a": 1}').status_code == 400
    assert client.post("/api/inspect", data={"file_id": "nope"}).status_code == 404


def test_forecast_job_schema(client):
    file_id = upload(client, "gol_stagionali.csv").json()["file_id"]
    r = client.post("/api/forecast", json={"file_id": file_id, "time_col": "Stagione_Anno", "value_col": "Gol",
                                           "models": ["Timestral-5M"], "horizon": 3, "backtest_windows": 6})
    assert r.status_code == 200
    body = wait_job(client, r.json()["job_id"])
    assert body["status"] == "done", body
    res = body["result"]
    meta = res["meta"]
    assert meta["frequency"] == "season" and meta["season_length"] is None
    assert (meta["n_obs"], meta["n_missing"], meta["horizon"]) == (10, 0, 3)
    assert (meta["backtest_horizon"], meta["backtest_windows"]) == (1, 6)
    assert res["history"][0] == {"t": "2016-2017", "y": 9.0}
    assert res["baselines"] == ["naive", "mean_k"]
    m = res["models"]["Timestral-5M"]
    assert m["backtest"][0] == {"origin": "2019-2020", "t": "2020-2021", "step": 1, "y": 19.0,
                                "p10": m["backtest"][0]["p10"], "p50": 21.0, "p90": m["backtest"][0]["p90"],
                                "naive": 21.0, "mean_k": 16.0}
    assert m["metrics"]["naive"]["mae"] == pytest.approx(3.0)
    assert m["metrics"]["mean_k"]["mae"] == pytest.approx(4.7222, abs=1e-3)
    assert set(m["metrics"]["model"]) == {"mae", "rmse", "smape", "mase", "coverage_80", "width_80", "wql"}
    assert [f["t"] for f in m["forecast"]] == ["2026-2027", "2027-2028", "2028-2029"]
    assert len(m["forecast"][0]["quantiles"]) == 21
    assert m["summary"].startswith("Con Timestral-5M il modello")


def test_forecast_monthly_has_seasonal_naive(client):
    file_id = upload(client, "vendite_mensili.csv").json()["file_id"]
    r = client.post("/api/forecast", json={"file_id": file_id, "time_col": "Mese", "value_col": "Vendite",
                                           "models": ["Timestral-5M"], "horizon": 12})
    res = wait_job(client, r.json()["job_id"])["result"]
    assert res["meta"]["frequency"] == "monthly" and res["meta"]["season_length"] == 12
    assert "seasonal_naive" in res["baselines"]
    assert [f["t"] for f in res["models"]["Timestral-5M"]["forecast"]][:2] == ["2025-01", "2025-02"]


def test_forecast_group_keeps_gaps(client):
    file_id = upload(client, "sensore_orario.csv").json()["file_id"]
    r = client.post("/api/forecast", json={"file_id": file_id, "time_col": "timestamp", "value_col": "temperatura",
                                           "group_col": "sensore", "group_value": "sensore_b",
                                           "models": ["Timestral-5M"], "horizon": 24})
    res = wait_job(client, r.json()["job_id"])["result"]
    assert res["meta"]["group"] == "sensore_b" and res["meta"]["frequency"] == "hourly"
    assert res["meta"]["n_missing"] > 0
    assert sum(h["y"] is None for h in res["history"]) == res["meta"]["n_missing"]


@pytest.mark.parametrize(("name", "value_col", "fragment"), [
    ("troppo_corto.csv", "valore", "almeno 8"),
    ("gol_stagionali.csv", "Squadra", "non contiene valori numerici"),
])
def test_forecast_data_errors_are_readable(client, name, value_col, fragment):
    body = upload(client, name).json()
    r = client.post("/api/forecast", json={"file_id": body["file_id"], "time_col": body["suggested_time_col"],
                                           "value_col": value_col, "models": ["Timestral-5M"]})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "error"
    assert fragment in job["message"] and "Traceback" not in job["message"]


def test_forecast_request_validation(client):
    file_id = upload(client, "gol_stagionali.csv").json()["file_id"]
    base = {"file_id": file_id, "time_col": "Stagione_Anno", "value_col": "Gol"}
    assert client.post("/api/forecast", json={**base, "models": ["Timestral-1B"]}).status_code == 422
    assert client.post("/api/forecast", json={**base, "backtest_windows": 51}).status_code == 422
    assert client.post("/api/forecast", json={**base, "time_col": "Boh"}).status_code == 400
    assert client.post("/api/forecast", json={**base, "file_id": "x"}).status_code == 404


def test_cors_only_frontend_origin(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    ko = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in ko.headers
