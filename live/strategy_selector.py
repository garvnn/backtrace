"""
Strategy selector for live trading: pick Momentum vs Mean Reversion per ticker.

Selection uses only the first 70% of the history (in-sample training).
Out-of-sample metrics on the last 30% are returned for logging only, not for choosing the winner.
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
from trading_constants import STRATEGY_SELECTOR_TRAIN_FRACTION

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
    Run backtests on train (first 70%) only to pick Momentum vs MA Crossover.
    Profit probabilities on validation (last 30%) are computed for reporting only.

    Returns:
        (winner_strategy_class, prob_mom_train, prob_ma_train, prob_mom_val, prob_ma_val)
    """
    empty = (MomentumStrategy, 0.0, 0.0, 0.0, 0.0)
    if data is None or not isinstance(data, pd.DataFrame) or data.empty:
        return empty
    if lookback_days is not None and lookback_days > 0 and len(data) > lookback_days:
        data = data.iloc[-int(lookback_days) :].copy()
    if len(data) < MIN_LOOKBACK_ROWS:
        return empty

    split_idx = int(len(data) * STRATEGY_SELECTOR_TRAIN_FRACTION)
    if split_idx < MIN_LOOKBACK_ROWS or len(data) - split_idx < 2:
        return empty

    train = data.iloc[:split_idx]
    val = data.iloc[split_idx:]

    engine = BacktestEngine()

    try:
        res_mom_tr = engine.run(train, MomentumStrategy())
        res_ma_tr = engine.run(train, MeanReversionStrategy())
    except Exception:
        return empty

    prob_mom_tr = profit_probability_from_backtest(res_mom_tr.get("portfolio_values"))
    prob_ma_tr = profit_probability_from_backtest(res_ma_tr.get("portfolio_values"))

    if abs(prob_mom_tr - prob_ma_tr) < 1e-6:
        ret_mom = res_mom_tr.get("total_return", 0.0) or 0.0
        ret_ma = res_ma_tr.get("total_return", 0.0) or 0.0
        winner = MeanReversionStrategy if ret_ma > ret_mom else MomentumStrategy
    else:
        winner = MeanReversionStrategy if prob_ma_tr > prob_mom_tr else MomentumStrategy

    try:
        res_mom_val = engine.run(val, MomentumStrategy())
        res_ma_val = engine.run(val, MeanReversionStrategy())
        prob_mom_val = profit_probability_from_backtest(res_mom_val.get("portfolio_values"))
        prob_ma_val = profit_probability_from_backtest(res_ma_val.get("portfolio_values"))
    except Exception:
        prob_mom_val, prob_ma_val = 0.0, 0.0

    return winner, prob_mom_tr, prob_ma_tr, prob_mom_val, prob_ma_val
