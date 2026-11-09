import numpy as np
import pytest

from app import metrics
from app.backtest import (
    SeriesInput,
    baseline_backtest,
    best_baseline,
    evaluate,
    mean_k_window,
    model_backtest,
    plan_backtest,
    quantile_index,
    seasonal_naive_enabled,
    seasonal_naive_forecast,
    summary_sentence,
    targets,
)

GOL = np.array([9, 18, 9, 21, 19, 25, 28, 27, 22, 23], dtype=float)
LEVELS = (0.1, 0.5, 0.9)


class FakeModel:
    """Prevede l'ultimo valore osservato ± 1 su tutti i passi e registra i contesti ricevuti."""

    quantile_levels = LEVELS

    def __init__(self):
        self.contexts = []

    def predict(self, contexts, horizon):
        self.contexts.extend(contexts)
        last = np.array([c.target[np.isfinite(c.target)][-1] for c in contexts])
        q = np.stack([last - 1, last, last + 1], axis=-1)
        return np.repeat(q[:, None, :], horizon, axis=1)


# --------------------------------------------------------------------------- metriche a mano


def test_mae_rmse_ignore_nan():
    y = np.array([1.0, 2.0, np.nan, 4.0])
    yhat = np.array([2.0, 2.0, 100.0, 1.0])
    assert metrics.mae(y, yhat) == pytest.approx((1 + 0 + 3) / 3)
    assert metrics.rmse(y, yhat) == pytest.approx(np.sqrt((1 + 0 + 9) / 3))


def test_smape_skips_zero_denominator():
    assert metrics.smape(np.array([1.0, 0.0, 2.0]), np.array([3.0, 0.0, 2.0])) == pytest.approx(50.0)


def test_mase_by_hand():
    y = np.array([0.0, 2.0, 4.0, 6.0, 10.0])
    plan = plan_backtest(len(y), horizon=3, requested_windows=10)
    assert plan.horizon == 1 and plan.origins == (4,)
    base, k = baseline_backtest(y, plan, None)
    assert k == 3
    ev = evaluate(y, plan, FakeModel().predict([SeriesInput(y).context(4, 1)], 1), LEVELS, base, None)
    # scala naive in-sample su [0, 2, 4, 6] = 2; naive prevede 6 (errore 4), media 3 prevede 4 (errore 6)
    assert ev.baselines["naive"]["mase"] == pytest.approx(2.0)
    assert ev.baselines["mean_k"]["mase"] == pytest.approx(3.0)
    assert ev.model["mae"] == pytest.approx(4.0)


def test_naive_scale_seasonal_lag_and_degenerate():
    assert metrics.naive_scale(np.array([1.0, 5.0, 2.0, 6.0]), lag=2) == pytest.approx(1.0)
    assert np.isnan(metrics.naive_scale(np.array([3.0, 3.0, 3.0])))
    assert np.isnan(metrics.naive_scale(np.array([3.0])))


def test_coverage_width_wql_by_hand():
    y = np.array([2.0])
    q = np.array([[1.0, 2.0, 3.0]])
    assert metrics.interval_coverage(y, q[:, 0], q[:, 2]) == 1.0
    assert metrics.interval_width(q[:, 0], q[:, 2]) == 2.0
    # pinball: 0.1·1, 0, 0.1·1 → 2·pinball/|y| = [0.1, 0, 0.1] → media 1/15
    assert metrics.wql(y, q, LEVELS) == pytest.approx(0.2 / 3)
    assert metrics.interval_coverage(np.array([5.0]), q[:, 0], q[:, 2]) == 0.0


# --------------------------------------------------------------------------- finestre


def test_plan_short_series_eight_points():
    plan = plan_backtest(8, horizon=5, requested_windows=10)
    assert plan.horizon == 1
    assert plan.min_context == 4
    assert plan.origins == (4, 5, 6, 7)


def test_plan_gol_six_windows():
    plan = plan_backtest(10, horizon=3, requested_windows=6)
    assert plan.horizon == 1 and plan.origins == (4, 5, 6, 7, 8, 9)
    assert plan_backtest(10, horizon=3, requested_windows=50).windows == 6


def test_plan_long_series_non_overlapping():
    plan = plan_backtest(100, horizon=12, requested_windows=10)
    assert plan.horizon == 12 and plan.min_context == 24
    assert plan.windows == 6  # (100 - 24) // 12
    assert plan.origins[-1] + 12 == 100
    assert np.all(np.diff(plan.origins) == 12)


def test_plan_caps_windows_and_reduces_long_horizon():
    assert plan_backtest(1000, horizon=1, requested_windows=500).windows == 50
    plan = plan_backtest(40, horizon=30, requested_windows=10)
    assert plan.reduced_horizon and plan.horizon == 13
    assert plan.windows >= 1 and plan.origins[0] >= plan.min_context


def test_contexts_use_only_the_past():
    model = FakeModel()
    plan = plan_backtest(len(GOL), 1, 6)
    model_backtest(model, SeriesInput(GOL), plan)
    for o, ctx in zip(plan.origins, model.contexts):
        assert np.array_equal(ctx.target, GOL[:o])


# --------------------------------------------------------------------------- baseline


def test_gol_baselines_reproduce_reference():
    plan = plan_backtest(len(GOL), horizon=3, requested_windows=6)
    base, k = baseline_backtest(GOL, plan, None)
    assert k == 3
    assert set(base) == {"naive", "mean_k"}
    truth = targets(GOL, plan)
    assert metrics.mae(truth, base["naive"]) == pytest.approx(3.0)
    assert metrics.mae(truth, base["mean_k"]) == pytest.approx(4.7222, abs=1e-3)


def test_seasonal_naive_indices():
    ctx = np.arange(10.0)
    assert seasonal_naive_forecast(ctx, 6, 4).tolist() == [6, 7, 8, 9, 6, 7]


def test_seasonal_naive_needs_two_cycles():
    assert mean_k_window(100, 12) == 12 and mean_k_window(100, None) == 7 and mean_k_window(20, 12) == 3
    plan = plan_backtest(96, horizon=12, requested_windows=10)
    assert seasonal_naive_enabled(plan, 12)
    assert not seasonal_naive_enabled(plan, None)
    assert plan_backtest(30, 3, 3).origins == (21, 24, 27)
    assert not seasonal_naive_enabled(plan_backtest(30, 3, 3), 12)  # 21 punti < 2 cicli da 12
    base, _ = baseline_backtest(np.arange(96.0), plan, 12)
    assert "seasonal_naive" in base


def test_baselines_skip_missing_values():
    y = np.array([1.0, 2.0, 3.0, np.nan, 5.0, np.nan, 7.0, 8.0])
    plan = plan_backtest(len(y), 1, 10)
    base, _ = baseline_backtest(y, plan, None)
    assert np.isfinite(base["naive"]).all()
    assert base["naive"][:, 0].tolist() == [3.0, 5.0, 5.0, 7.0]  # il NaN finale del contesto viene saltato
    assert base["mean_k"][0, 0] == pytest.approx(2.0)


def test_quantile_index_nearest_level():
    levels = (0.01, 0.05, 0.1, 0.15, 0.5, 0.9, 0.95, 0.99)
    assert quantile_index(levels, 0.1) == 2
    assert quantile_index(levels, 0.1 + 1e-12) == 2
    assert quantile_index(levels, 0.9) == 5


def test_summary_sentence():
    plan = plan_backtest(len(GOL), 3, 6)
    base, k = baseline_backtest(GOL, plan, None)
    q = FakeModel().predict([SeriesInput(GOL).context(o, 1) for o in plan.origins], 1)
    ev = evaluate(GOL, plan, q, LEVELS, base, None)
    assert best_baseline(ev) == ("naive", pytest.approx(3.0))
    text = summary_sentence("Timestral-5M", ev, k)
    assert text.startswith("Con Timestral-5M il modello non batte la baseline migliore (naive (ultimo valore))")
    assert "3,00 contro 3,00" in text
