"""
Synthetic tests for analytics/divergence (no Yahoo/Alpaca network).
"""

import os
import sys

import pandas as pd

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from analytics.divergence import (
    align_and_rebase,
    compare_metrics,
    load_backtest_equity_series,
    load_live_equity_series,
    rolling_performance_gaps,
)
from trading_constants import INITIAL_CAPITAL


def test_align_and_compare_positive_delta_when_live_outperforms():
    dates = pd.date_range("2024-01-01", periods=25, freq="B")
    bt = pd.Series(100_000.0, index=dates, dtype=float)
    live = pd.Series(100_000.0, index=dates, dtype=float)
    for i in range(1, len(dates)):
        bt.iloc[i] = bt.iloc[i - 1] * 1.001
        live.iloc[i] = live.iloc[i - 1] * 1.002
    bta, lva, meta = align_and_rebase(bt, live, None, None)
    assert "error" not in meta
    _, _, delta = compare_metrics(bta, lva, INITIAL_CAPITAL)
    assert delta["return"] > 0, "live scaled higher should beat backtest after common rebase"


def test_load_backtest_equity_series_sorts_and_dedupes():
    row = {
        "equity_curve": [
            {"timestamp": "2024-01-03", "portfolio_value": 100000},
            {"timestamp": "2024-01-02", "portfolio_value": 99000},
            {"timestamp": "2024-01-02", "portfolio_value": 99500},
        ]
    }
    s = load_backtest_equity_series(row)
    assert len(s) == 2
    # Sorted by date; duplicate 2024-01-02 keeps last value 99500
    assert s.iloc[0] == 99500 and s.iloc[-1] == 100000


def test_load_live_respects_meanreversion_alias():
    snaps = [
        (1, "2024-01-02T16:30:00", "MA Crossover", 100000.0, 50000.0, "{}"),
        (2, "2024-01-03T16:30:00", "MA Crossover", 101000.0, 51000.0, "{}"),
    ]
    s = load_live_equity_series(snaps, "MeanReversion", "2024-01-01", "2024-01-31")
    assert len(s) == 2


def test_rolling_largest_divergence_sorted():
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    bt = pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)
    live = bt + 10.0
    bta, lva, _ = align_and_rebase(bt, live, None, None)
    roll = rolling_performance_gaps(bta, lva, windows=(7, 14), top_n=3)
    assert len(roll["window_7d"]) > 0
    top = roll["largest_divergence_periods"]
    assert len(top) <= 3
    if len(top) >= 2:
        assert abs(top[0]["delta_return"]) >= abs(top[1]["delta_return"])


def main():
    print("=" * 60)
    print("DIVERGENCE ANALYZER TESTS")
    print("=" * 60)
    failed = []
    for name, fn in [
        ("align_and_compare", test_align_and_compare_positive_delta_when_live_outperforms),
        ("load_backtest_equity_series", test_load_backtest_equity_series_sorts_and_dedupes),
        ("load_live_alias", test_load_live_respects_meanreversion_alias),
        ("rolling", test_rolling_largest_divergence_sorted),
    ]:
        try:
            fn()
            print(f"  [PASS] {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed.append(name)
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
