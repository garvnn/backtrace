"""
Backtest invariants for BackTrace.

Properties that must hold for any strategy on any price series. No network, no
database — synthetic OHLCV only, so these run anywhere in under a second.

These began as invariants over the live trading database (cash never negative,
portfolio value reconciles to cash plus positions, position cap respected).
When the live layer was removed, the DB-backed versions retired with it, but the
properties themselves apply just as well to the backtest engine — where a
violation means the engine is lying about returns, which is the thing this
project exists to measure.

    pytest tests/test_invariants.py -v
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.backtest_engine import BacktestEngine
from strategies.base import Strategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.stat_arb import StatArbStrategy
from trading_constants import INITIAL_CAPITAL, MAX_DOLLAR_PER_STOCK

VALID_SIGNALS = {-1, 0, 1}

# A long-only strategy holds at most one capped position at a time, so the worst
# case is that position going to zero. The bound is not exactly the cap because
# quantity is sized off the prior close while the fill happens at the next open:
# an overnight gap up can push the entry notional slightly above the cap.
GAP_ALLOWANCE = 1.15


def _make_synthetic_ohlcv(n_rows=400, seed=42):
    """Synthetic OHLCV on a random walk. Long enough for a 200-bar moving average."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp("2024-12-31"), periods=n_rows, freq="B")
    close = 100.0 + np.cumsum(rng.normal(0, 1, n_rows))
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.002, n_rows)),
            "High": close * (1 + np.abs(rng.normal(0, 0.005, n_rows))),
            "Low": close * (1 - np.abs(rng.normal(0, 0.005, n_rows))),
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, n_rows),
        },
        index=dates,
    )


def _assert_valid_signals(series, strategy_name):
    values = set(series.dropna().unique())
    invalid = values - VALID_SIGNALS
    assert not invalid, f"{strategy_name} produced invalid signals: {invalid}"


class _AlwaysFlat(Strategy):
    """Never takes a position. Used to pin the no-trade baseline."""

    def __init__(self):
        super().__init__(name="AlwaysFlat")

    def generate_signals(self, data):
        return pd.Series(0, index=data.index)


@pytest.fixture(scope="module")
def data():
    return _make_synthetic_ohlcv()


@pytest.mark.invariant
def test_signals_are_valid_values(data):
    """
    WHAT: Every strategy's generate_signals output must be in {-1, 0, 1}.
    WHY: An out-of-domain signal is silently reinterpreted downstream, so the
         backtest would report returns for a position nobody intended.
    """
    data_b = data * 1.05

    _assert_valid_signals(MomentumStrategy(lookback_period=120).generate_signals(data), "Momentum")
    _assert_valid_signals(
        MeanReversionStrategy(short_window=50, long_window=200).generate_signals(data),
        "MA Crossover",
    )

    sig_a, sig_b = StatArbStrategy("AAPL", "MSFT", lookback=60).generate_signals(data, data_b)
    _assert_valid_signals(sig_a, "Stat Arb (leg A)")
    _assert_valid_signals(sig_b, "Stat Arb (leg B)")


@pytest.mark.invariant
def test_equity_never_negative(data):
    """
    WHAT: Portfolio value must be >= 0 at every bar.
    WHY: A long-only strategy cannot owe money. Negative equity means cash
         accounting drifted — the direct backtest analogue of the live
         "cash never negative" check.
    """
    for strategy in (MomentumStrategy(), MeanReversionStrategy()):
        pv = BacktestEngine().run(data, strategy)["portfolio_values"]
        assert (pv >= 0).all(), f"{strategy.name}: equity went negative at {pv[pv < 0].index.tolist()[:3]}"


@pytest.mark.invariant
def test_equity_starts_at_initial_capital(data):
    """
    WHAT: The first bar's portfolio value equals the configured initial capital.
    WHY: No position can be held before the first signal exists. A non-matching
         first value means the engine is filling on bar 0, which is lookahead.
    """
    engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    for strategy in (MomentumStrategy(), MeanReversionStrategy(), _AlwaysFlat()):
        pv = engine.run(data, strategy)["portfolio_values"]
        assert float(pv.iloc[0]) == pytest.approx(INITIAL_CAPITAL), (
            f"{strategy.name}: first bar is {pv.iloc[0]}, expected {INITIAL_CAPITAL}"
        )


@pytest.mark.invariant
def test_flat_strategy_never_trades(data):
    """
    WHAT: A strategy that always signals 0 produces zero trades and constant equity.
    WHY: Pins the no-op baseline. If equity moves without a position, the engine
         is marking to market something it does not hold.
    """
    result = BacktestEngine().run(data, _AlwaysFlat())
    pv = result["portfolio_values"]
    assert result["trades"] == 0, f"flat strategy placed {result['trades']} trades"
    assert pv.nunique() == 1, "equity moved with no position held"
    assert float(result["total_return"]) == pytest.approx(0.0)


@pytest.mark.invariant
def test_drawdown_bounded_by_position_cap(data):
    """
    WHAT: Peak-to-trough dollar drawdown cannot exceed MAX_DOLLAR_PER_STOCK
          plus an overnight-gap allowance.
    WHY: Long-only, one capped position at a time, so the worst case is that
          position going to zero. A breach means sizing ignored the cap — the
          backtest analogue of the live "position cap respected" invariant, and
          the check that would catch a buying-power-vs-cash sizing error.
    """
    limit = MAX_DOLLAR_PER_STOCK * GAP_ALLOWANCE
    for strategy in (MomentumStrategy(), MeanReversionStrategy()):
        pv = BacktestEngine().run(data, strategy)["portfolio_values"]
        drawdown = float((pv.expanding().max() - pv).max())
        assert drawdown <= limit, (
            f"{strategy.name}: drawdown ${drawdown:,.2f} exceeds cap ${limit:,.2f}"
        )


@pytest.mark.invariant
def test_backtest_is_deterministic(data):
    """
    WHAT: Identical inputs must produce a bit-identical equity curve and trade count.
    WHY: Saved runs of the same (strategy, ticker, window) were found differing 5x
         in total return. That turned out to be unrecorded parameters rather than
         engine nondeterminism — this test keeps it that way, so a future
         divergence can only mean the parameters differed.
    """
    for strategy_factory in (MomentumStrategy, MeanReversionStrategy):
        first = BacktestEngine().run(data, strategy_factory())
        second = BacktestEngine().run(data, strategy_factory())
        pd.testing.assert_series_equal(first["portfolio_values"], second["portfolio_values"])
        assert first["trades"] == second["trades"]
        assert first["total_return"] == second["total_return"]


@pytest.mark.invariant
def test_equity_index_matches_price_index(data):
    """
    WHAT: The equity curve is indexed exactly by the input price index.
    WHY: A dropped or shifted bar silently misaligns returns against dates, which
         would corrupt every downstream metric and the attribution report.
    """
    for strategy in (MomentumStrategy(), MeanReversionStrategy(), _AlwaysFlat()):
        pv = BacktestEngine().run(data, strategy)["portfolio_values"]
        pd.testing.assert_index_equal(pv.index, data.index)
