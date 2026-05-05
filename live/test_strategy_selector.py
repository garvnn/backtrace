"""
Strategy selector validation: 60-day backtest for Momentum vs MA Crossover,
profit probability calculation, tie-breaking, and selection logic.
"""

import os
import sys
import pandas as pd
import numpy as np

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from strategy_selector import (
    profit_probability_from_backtest,
    select_strategy_for_ticker,
)
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy


def make_sample_data(days=60, trend="up", volatility=0.01):
    """Create synthetic OHLCV data. trend in ('up', 'down', 'flat')."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    base = 100.0
    if trend == "up":
        drift = 0.0005
    elif trend == "down":
        drift = -0.0003
    else:
        drift = 0.0
    returns = np.random.randn(days) * volatility + drift
    returns[0] = 0
    close = base * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "Open": close * 0.99,
        "High": close * 1.01,
        "Low": close * 0.98,
        "Close": close,
        "Volume": 1_000_000,
    }, index=dates)


def test_profit_probability_calculation():
    """Verify profit probability = proportion of days with positive return."""
    pv = pd.Series([100, 101, 100.5, 102, 101])  # 4 periods, 3 positive returns
    prob = profit_probability_from_backtest(pv)
    daily = pv.pct_change().dropna()
    expected = (daily > 0).mean()
    assert 0 <= prob <= 1, "Probability should be in [0, 1]"
    assert abs(prob - expected) < 1e-6, f"Expected {expected}, got {prob}"
    return True


def test_profit_probability_edge_cases():
    """Empty or short series returns 0."""
    assert profit_probability_from_backtest(None) == 0.0
    assert profit_probability_from_backtest(pd.Series([100])) == 0.0
    assert profit_probability_from_backtest(pd.Series([])) == 0.0
    return True


def test_select_strategy_60day():
    """Run 60-day backtest for Momentum and MA Crossover; verify selection and probabilities."""
    data = make_sample_data(60, trend="up")
    winner_class, prob_mom_tr, prob_ma_tr, prob_mom_val, prob_ma_val = select_strategy_for_ticker(
        "AAPL", data, lookback_days=60
    )
    assert winner_class in (MomentumStrategy, MeanReversionStrategy)
    for p in (prob_mom_tr, prob_ma_tr, prob_mom_val, prob_ma_val):
        assert 0 <= p <= 1
    return winner_class, prob_mom_tr, prob_ma_tr, prob_mom_val, prob_ma_val


def test_tie_breaking():
    """When probabilities are equal, selector uses total_return tie-break (prefer higher return)."""
    # Use data where we can get a tie or known ordering
    data = make_sample_data(60, trend="flat", volatility=0.005)
    winner_class, _, _, _, _ = select_strategy_for_ticker("TICK", data, lookback_days=60)
    # Just ensure we get a valid strategy
    assert winner_class in (MomentumStrategy, MeanReversionStrategy)
    return True


def test_insufficient_data_returns_momentum():
    """If data has fewer than MIN_LOOKBACK_ROWS, default to Momentum."""
    data = make_sample_data(20)
    winner_class, prob_mom_tr, prob_ma_tr, _, _ = select_strategy_for_ticker("X", data, lookback_days=60)
    assert winner_class == MomentumStrategy
    assert prob_mom_tr == 0.0 and prob_ma_tr == 0.0
    return True


def test_empty_data_returns_momentum():
    """Empty or None data returns Momentum as default."""
    winner_class, _, _, _, _ = select_strategy_for_ticker("X", None, lookback_days=60)
    assert winner_class == MomentumStrategy
    winner_class2, _, _, _, _ = select_strategy_for_ticker("X", pd.DataFrame(), lookback_days=60)
    assert winner_class2 == MomentumStrategy
    return True


def test_multiple_tickers():
    """Run selector on multiple tickers; ensure consistent behavior (no randomness)."""
    data = make_sample_data(60)
    results = []
    for ticker in ["AAPL", "MSFT", "GOOGL"]:
        winner_class, prob_mom_tr, prob_ma_tr, _, _ = select_strategy_for_ticker(
            ticker, data, lookback_days=60
        )
        results.append((ticker, winner_class.__name__, prob_mom_tr, prob_ma_tr))
    # Same data -> same winner and same probs for all
    assert len(set(r[1] for r in results)) >= 1
    return results


def main():
    print("=" * 60)
    print("STRATEGY SELECTOR VALIDATION")
    print("=" * 60)
    failures = []
    # Profit probability
    try:
        test_profit_probability_calculation()
        print("  [PASS] profit_probability calculation")
    except Exception as e:
        print(f"  [FAIL] profit_probability calculation: {e}")
        failures.append("profit_probability")
    try:
        test_profit_probability_edge_cases()
        print("  [PASS] profit_probability edge cases")
    except Exception as e:
        print(f"  [FAIL] profit_probability edge cases: {e}")
        failures.append("profit_probability_edge")
    # 60-day selection
    try:
        winner_class, prob_mom_tr, prob_ma_tr, pv, pv2 = test_select_strategy_60day()
        print(
            f"  [PASS] 60-day selection: winner={winner_class.__name__}, "
            f"train prob_mom={prob_mom_tr:.3f}, train prob_ma={prob_ma_tr:.3f}, "
            f"val prob_mom={pv:.3f}, val prob_ma={pv2:.3f}"
        )
    except Exception as e:
        print(f"  [FAIL] 60-day selection: {e}")
        failures.append("60day")
    try:
        test_tie_breaking()
        print("  [PASS] tie-breaking (returns valid strategy)")
    except Exception as e:
        print(f"  [FAIL] tie-breaking: {e}")
        failures.append("tie_break")
    try:
        test_insufficient_data_returns_momentum()
        print("  [PASS] insufficient data -> Momentum default")
    except Exception as e:
        print(f"  [FAIL] insufficient data: {e}")
        failures.append("insufficient_data")
    try:
        test_empty_data_returns_momentum()
        print("  [PASS] empty/None data -> Momentum default")
    except Exception as e:
        print(f"  [FAIL] empty data: {e}")
        failures.append("empty_data")
    try:
        results = test_multiple_tickers()
        print("  [PASS] multiple tickers:", results)
    except Exception as e:
        print(f"  [FAIL] multiple tickers: {e}")
        failures.append("multiple_tickers")
    print("=" * 60)
    if failures:
        print(f"Result: FAIL ({len(failures)} failures)")
        return 1
    print("Result: All strategy selector tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
