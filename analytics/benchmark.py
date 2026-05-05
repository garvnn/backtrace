"""
Benchmark helpers: equity curves, daily returns, Sharpe, max drawdown from a value series.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def equity_series_to_curve_list(series: pd.Series) -> list:
    """Serialize a pandas Series of portfolio values to API-friendly points."""
    out = []
    for i in range(len(series)):
        ts = series.index[i]
        ts_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        out.append({"timestamp": ts_str, "portfolio_value": float(series.iloc[i])})
    return out


def daily_returns_from_equity(series: pd.Series) -> pd.Series:
    return series.pct_change().dropna()


def sharpe_from_daily_returns(daily_returns: pd.Series) -> float:
    if len(daily_returns) == 0 or daily_returns.std() == 0 or pd.isna(daily_returns.std()):
        return 0.0
    return float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))


def max_drawdown_from_equity(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    running_max = series.expanding().max()
    drawdown = (series - running_max) / running_max
    return float(drawdown.min())


def total_return_from_equity(series: pd.Series, initial_capital: float) -> float:
    if len(series) == 0 or initial_capital == 0:
        return 0.0
    return float(series.iloc[-1] / initial_capital) - 1.0


def metrics_from_equity_series(series: pd.Series, initial_capital: float) -> dict:
    """Sharpe, max drawdown, total return; daily_returns as list of {date, return}."""
    dr = daily_returns_from_equity(series)
    daily_returns_list = []
    for idx, val in dr.items():
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        if pd.notna(val):
            daily_returns_list.append({"date": d, "return": float(val)})
    return {
        "total_return": total_return_from_equity(series, initial_capital),
        "sharpe_ratio": sharpe_from_daily_returns(dr),
        "max_drawdown": max_drawdown_from_equity(series),
        "daily_returns": daily_returns_list,
    }


def metrics_from_sparse_equity_points(
    timestamps: list,
    values: list,
    initial_capital: float,
) -> dict:
    """
    Metrics from irregular snapshots (e.g. live portfolio history).
    Uses day-level pct_change between consecutive points (not perfect but matches sparse data).
    """
    if len(values) < 2:
        return {
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "daily_returns": [],
        }
    s = pd.Series(values, index=pd.to_datetime(timestamps))
    s = s.sort_index()
    # collapse duplicate timestamps: last wins
    s = s[~s.index.duplicated(keep="last")]
    dr = s.pct_change().dropna()
    daily_returns_list = []
    for idx, val in dr.items():
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        if pd.notna(val):
            daily_returns_list.append({"date": d, "return": float(val)})
    total_ret = float(s.iloc[-1] / initial_capital) - 1.0 if initial_capital else 0.0
    running_max = s.expanding().max()
    dd = (s - running_max) / running_max
    max_dd = float(dd.min()) if len(s) else 0.0
    sharpe = sharpe_from_daily_returns(dr) if len(dr) else 0.0
    return {
        "total_return": total_ret,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "daily_returns": daily_returns_list,
    }
