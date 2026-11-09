"""Test con Timestral reale (marker `slow`): servono il pacchetto e i pesi della 5M (scaricati al primo uso)."""

import numpy as np
import pytest

from app.backtest import SeriesInput, baseline_backtest, evaluate, model_backtest, plan_backtest, targets
from app.loader import read_table
from app.metrics import mae
from app.models import ModelRegistry, timestral_available
from app.preprocessing import prepare_series
from tests.conftest import read_sample

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not timestral_available(), reason="pacchetto timestral non installato"),
]


@pytest.fixture(scope="module")
def registry():
    return ModelRegistry()


def synthetic(n=400, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    y = 50 + 0.05 * t + 10 * np.sin(2 * np.pi * t / 24) + rng.normal(0, 1, n)
    y[[37, 38, 150, 151, 152]] = np.nan
    return y


def test_batched_origins_match_single_calls(registry):
    """Il batching (contesti allineati a destra con NaN) deve coincidere con le chiamate singole entro 1e-4."""
    model = registry.get("5M")
    series = SeriesInput(synthetic())
    plan = plan_backtest(len(series.y), horizon=24, requested_windows=10)
    contexts = [series.context(o, plan.horizon) for o in plan.origins]
    model.batch = True
    batched = model.predict(contexts, plan.horizon)
    model.batch = False
    try:
        single = model.predict(contexts, plan.horizon)
    finally:
        model.batch = True
    assert batched.shape == single.shape == (plan.windows, 24, 21)
    np.testing.assert_allclose(batched, single, atol=1e-4, rtol=0)


def test_gol_reproducibility_5m(registry):
    df = read_table("gol.csv", read_sample("gol_stagionali.csv"))
    s = prepare_series(df, "Stagione_Anno", "Gol")
    plan = plan_backtest(s.n_obs, horizon=3, requested_windows=6)
    assert plan.horizon == 1 and plan.windows == 6
    model = registry.get("5M")
    q = model_backtest(model, SeriesInput(s.y), plan)
    base, k = baseline_backtest(s.y, plan, s.season_length)
    ev = evaluate(s.y, plan, q, model.quantile_levels, base, s.season_length)
    assert k == 3
    assert ev.model["mae"] == pytest.approx(4.251, abs=0.01)
    assert ev.baselines["naive"]["mae"] == pytest.approx(3.000, abs=0.01)
    assert ev.baselines["mean_k"]["mae"] == pytest.approx(4.722, abs=0.01)
    assert mae(targets(s.y, plan), q[..., 10]) == pytest.approx(ev.model["mae"])


def test_synthetic_series_beats_naive(registry):
    y = synthetic()
    plan = plan_backtest(len(y), horizon=24, requested_windows=5)
    model = registry.get("5M")
    q = model_backtest(model, SeriesInput(y), plan)
    base, _ = baseline_backtest(y, plan, 24)
    ev = evaluate(y, plan, q, model.quantile_levels, base, 24)
    assert "seasonal_naive" in ev.baselines
    assert ev.model["mae"] < ev.baselines["naive"]["mae"]
    assert 0 <= ev.model["coverage_80"] <= 1 and ev.model["width_80"] > 0
