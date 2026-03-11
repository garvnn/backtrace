"""
Strategy selector for live trading: pick Momentum vs Mean Reversion per ticker using profit probability.

Used by the scheduler to run one strategy per ticker per day (the one with higher profit probability
over a short lookback backtest). Stat Arb is not used in live; it remains for backtesting only.
"""

import sys
import os

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

import pandas as pd

from engine.backtest_engine import BacktestEngine
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy


# Minimum number of rows for a valid backtest
MIN_LOOKBACK_ROWS = 30


def profit_probability_from_backtest(portfolio_values):
    """
    Compute profit probability as proportion of days with positive return.

    Args:
        portfolio_values: pandas Series of portfolio values (e.g. from BacktestEngine.run).

    Returns:
        Float in [0, 1]; 0.0 if empty or no returns.
    """
    if portfolio_values is None or len(portfolio_values) < 2:
        return 0.0
    daily_returns = portfolio_values.pct_change().dropna()
    if len(daily_returns) == 0:
        return 0.0
    return float((daily_returns > 0).mean())


def select_strategy_for_ticker(ticker, data, lookback_days=60):
    """
    Run short backtests for Momentum and Mean Reversion on the given data,
    compute profit probability for each, and return the winning strategy class.

    Args:
        ticker: Ticker symbol (for logging; not used in computation).
        data: DataFrame with 'Close' and same format as executor/backtest (Date index, OHLCV).
        lookback_days: Minimum number of days required; if data has fewer rows, returns Momentum as default.

    Returns:
        Tuple (winner_strategy_class, profit_prob_momentum, profit_prob_ma).
        winner_strategy_class is MomentumStrategy or MeanReversionStrategy (the class, not instance).
        On tie or error, prefers Momentum.
    """
    if data is None or not isinstance(data, pd.DataFrame) or data.empty:
        return MomentumStrategy, 0.0, 0.0
    if len(data) < MIN_LOOKBACK_ROWS:
        return MomentumStrategy, 0.0, 0.0

    engine = BacktestEngine(initial_capital=100000, commission=0.001)

    try:
        res_mom = engine.run(data, MomentumStrategy())
        res_ma = engine.run(data, MeanReversionStrategy())
    except Exception:
        return MomentumStrategy, 0.0, 0.0

    prob_mom = profit_probability_from_backtest(res_mom.get("portfolio_values"))
    prob_ma = profit_probability_from_backtest(res_ma.get("portfolio_values"))

    # Tie-break: use total_return
    if abs(prob_mom - prob_ma) < 1e-6:
        ret_mom = res_mom.get("total_return", 0.0) or 0.0
        ret_ma = res_ma.get("total_return", 0.0) or 0.0
        winner = MeanReversionStrategy if ret_ma > ret_mom else MomentumStrategy
    else:
        winner = MeanReversionStrategy if prob_ma > prob_mom else MomentumStrategy

    return winner, prob_mom, prob_ma
