"""Unit tests for analytics/robustness (no network)."""

import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analytics.robustness import (
    bootstrap_confidence_intervals,
    compute_robustness_score,
    walk_forward_validation,
)
from trading_constants import INITIAL_CAPITAL


def test_bootstrap_ci_width():
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.01, len(dates))
    eq = pd.Series(INITIAL_CAPITAL * np.cumprod(1.0 + r), index=dates)
    out = bootstrap_confidence_intervals(eq, n_samples=200, rng=np.random.default_rng(1))
    lo, hi = out["return_ci_95"]
    assert lo is not None and hi is not None
    assert lo <= hi


def test_compute_robustness_score_range():
    wf = {"aggregate": {"avg_return": 0.05, "return_std": 0.01, "n_windows": 5}}
    ps = {"stability_score": 0.5}
    boot = {"return_ci_95": [-0.02, 0.12], "distribution_summary": {"return_mean": 0.05}}
    reg = {"regimes": {"uptrend": {"return": 0.04}, "downtrend": {"return": 0.03}, "sideways": {"return": 0.02}}}
    s = compute_robustness_score(wf, ps, boot, reg)
    assert 0.0 <= s["robustness_score"] <= 1.0
    assert s["interpretation"] in ("robust", "moderate", "fragile")


def test_walk_forward_empty_short_data():
    df = pd.DataFrame({"Open": [1, 2], "Close": [1, 2]}, index=pd.date_range("2024-01-01", periods=2, freq="B"))
    out = walk_forward_validation(df, "Momentum", train_bars=120, test_bars=30)
    assert out["aggregate"]["n_windows"] == 0


def main():
    failed = []
    for name, fn in [
        ("bootstrap_ci", test_bootstrap_ci_width),
        ("robustness_score", test_compute_robustness_score_range),
        ("walk_forward_empty", test_walk_forward_empty_short_data),
    ]:
        try:
            fn()
            print(f"  [PASS] {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed.append(name)
    return 1 if failed else 0


if __name__ == "__main__":
    print("=" * 60)
    print("ROBUSTNESS TESTS")
    print("=" * 60)
    sys.exit(main())
