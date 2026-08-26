"""
Walk-forward validation, parameter sensitivity, bootstrap CIs, regime splits,
and composite robustness score. Uses existing BacktestEngine and benchmark metrics only.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "live"))

from analytics.benchmark import (
    daily_returns_from_equity,
    max_drawdown_from_equity,
    metrics_from_equity_series,
    sharpe_from_daily_returns,
)
from engine.backtest_engine import BacktestEngine
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.stat_arb import StatArbStrategy
from trading_constants import INITIAL_CAPITAL

def profit_probability_from_backtest(portfolio_values):
    """
    Fraction of days with a positive return. 0.0 if the series is too short.

    Was imported from live/strategy_selector.py behind a try/except. That module
    is gone (its 60-bar fitting window could never feed a 120- or 200-bar
    strategy, so it always returned Momentum), but the statistic itself is sound
    and walk-forward validation here fits on windows large enough to use it.
    """
    if portfolio_values is None or len(portfolio_values) < 2:
        return 0.0
    dr = portfolio_values.pct_change().dropna()
    return float((dr > 0).mean()) if len(dr) else 0.0


def _select_momentum_vs_ma_on_train(train: pd.DataFrame):
    """Strategy choice from train window only (matches live selector logic)."""
    if train is None or len(train) < 30:
        return MomentumStrategy
    engine = BacktestEngine()
    try:
        r_m = engine.run(train, MomentumStrategy())
        r_a = engine.run(train, MeanReversionStrategy())
    except Exception:
        return MomentumStrategy
    p_m = profit_probability_from_backtest(r_m.get("portfolio_values"))
    p_a = profit_probability_from_backtest(r_a.get("portfolio_values"))
    if abs(p_m - p_a) < 1e-6:
        ret_m = r_m.get("total_return", 0.0) or 0.0
        ret_a = r_a.get("total_return", 0.0) or 0.0
        return MeanReversionStrategy if ret_a > ret_m else MomentumStrategy
    return MeanReversionStrategy if p_a > p_m else MomentumStrategy


def _walk_forward_stat_arb(
    data_a: pd.DataFrame,
    data_b: pd.DataFrame,
    train_bars: int,
    test_bars: int,
    min_train: int,
    factory: Callable[[], StatArbStrategy],
) -> dict[str, Any]:
    common = data_a.index.intersection(data_b.index)
    data_a = data_a.loc[common].sort_index()
    data_b = data_b.loc[common].sort_index()
    windows: list[dict] = []
    engine = BacktestEngine()
    i = 0
    while i + train_bars + test_bars <= len(data_a):
        train = data_a.iloc[i : i + train_bars]
        test_a = data_a.iloc[i + train_bars : i + train_bars + test_bars]
        test_b = data_b.iloc[i + train_bars : i + train_bars + test_bars]
        if len(train) < min_train or len(test_a) < 5:
            i += test_bars
            continue
        tr0, tr1 = str(train.index[0].date()), str(train.index[-1].date())
        te0, te1 = str(test_a.index[0].date()), str(test_a.index[-1].date())
        try:
            res = engine.run_pair(test_a, test_b, factory())
            pv = res.get("portfolio_values")
            if pv is None or len(pv) < 2:
                raise ValueError("empty pv")
            m = metrics_from_equity_series(pv, INITIAL_CAPITAL)
            windows.append(
                {
                    "train_range": {"start": tr0, "end": tr1},
                    "test_range": {"start": te0, "end": te1},
                    "return": float(m["total_return"]),
                    "sharpe": float(m["sharpe_ratio"]),
                    "drawdown": float(m["max_drawdown"]),
                    "chosen_strategy": "Stat Arb",
                }
            )
        except Exception:
            pass
        i += test_bars

    rets = [w["return"] for w in windows]
    sharpes = [w["sharpe"] for w in windows]
    return {
        "windows": windows,
        "aggregate": {
            "avg_return": float(np.mean(rets)) if rets else None,
            "avg_sharpe": float(np.mean(sharpes)) if sharpes else None,
            "return_std": float(np.std(rets)) if rets else None,
            "sharpe_std": float(np.std(sharpes)) if sharpes else None,
            "n_windows": len(windows),
        },
    }


def walk_forward_validation(
    data: pd.DataFrame,
    strategy_name: str,
    *,
    train_bars: int = 120,
    test_bars: int = 30,
    min_train: int = 60,
    data_b: pd.DataFrame | None = None,
    stat_strategy_factory: Callable[[], StatArbStrategy] | None = None,
) -> dict[str, Any]:
    """
    Rolling train then test, advancing by test_bars.
    Single-name: pick Momentum vs MA on train; metrics on test. Stat Arb: pair factory on test slices.
    """
    if strategy_name == "Stat Arb" and data_b is not None and stat_strategy_factory is not None:
        return _walk_forward_stat_arb(data, data_b, train_bars, test_bars, min_train, stat_strategy_factory)

    windows: list[dict] = []
    if data is None or data.empty or len(data) < min_train + test_bars + 5:
        return {
            "windows": [],
            "aggregate": {
                "avg_return": None,
                "avg_sharpe": None,
                "return_std": None,
                "sharpe_std": None,
                "n_windows": 0,
            },
        }

    engine = BacktestEngine()
    i = 0
    while i + train_bars + test_bars <= len(data):
        train = data.iloc[i : i + train_bars]
        test = data.iloc[i + train_bars : i + train_bars + test_bars]
        if len(train) < min_train or len(test) < 5:
            i += test_bars
            continue
        tr0, tr1 = str(train.index[0].date()), str(train.index[-1].date())
        te0, te1 = str(test.index[0].date()), str(test.index[-1].date())
        try:
            winner = _select_momentum_vs_ma_on_train(train)
            res = engine.run(test, winner())
            pv = res.get("portfolio_values")
            if pv is None or len(pv) < 2:
                raise ValueError("empty pv")
            m = metrics_from_equity_series(pv, INITIAL_CAPITAL)
            windows.append(
                {
                    "train_range": {"start": tr0, "end": tr1},
                    "test_range": {"start": te0, "end": te1},
                    "return": float(m["total_return"]),
                    "sharpe": float(m["sharpe_ratio"]),
                    "drawdown": float(m["max_drawdown"]),
                    "chosen_strategy": winner.__name__,
                }
            )
        except Exception:
            pass
        i += test_bars

    rets = [w["return"] for w in windows]
    sharpes = [w["sharpe"] for w in windows]
    return {
        "windows": windows,
        "aggregate": {
            "avg_return": float(np.mean(rets)) if rets else None,
            "avg_sharpe": float(np.mean(sharpes)) if sharpes else None,
            "return_std": float(np.std(rets)) if rets else None,
            "sharpe_std": float(np.std(sharpes)) if sharpes else None,
            "n_windows": len(windows),
        },
    }


def parameter_sensitivity(
    data: pd.DataFrame,
    strategy_name: str,
    *,
    base_lookback_period: int = 120,
    base_short: int = 50,
    base_long: int = 200,
    base_stat_lookback: int = 60,
    base_entry: float = 2.0,
    base_exit: float = 0.5,
    data_b: pd.DataFrame | None = None,
    ticker_a: str = "",
    ticker_b: str = "",
) -> dict[str, Any]:
    """±20% grids; stability_score = std(returns) / max(|mean return|, 1e-6)."""
    engine = BacktestEngine()
    param_results: list[dict] = []
    returns: list[float] = []

    def pct_grid(base: float):
        return [base * 0.8, base * 1.0, base * 1.2]

    try:
        if strategy_name == "Stat Arb" and data_b is not None and ticker_a and ticker_b:
            for lb in [max(20, int(round(x))) for x in pct_grid(float(base_stat_lookback))]:
                for ent in pct_grid(base_entry):
                    for ex in [max(0.1, float(x)) for x in pct_grid(base_exit)]:
                        try:
                            tr = float(
                                engine.run_pair(
                                    data,
                                    data_b,
                                    StatArbStrategy(
                                        ticker_a,
                                        ticker_b,
                                        lookback=lb,
                                        entry_threshold=float(ent),
                                        exit_threshold=float(ex),
                                    ),
                                )["total_return"]
                            )
                            returns.append(tr)
                            param_results.append(
                                {
                                    "lookback": lb,
                                    "entry_threshold": float(ent),
                                    "exit_threshold": float(ex),
                                    "total_return": tr,
                                }
                            )
                        except Exception:
                            continue
        elif strategy_name in ("MeanReversion", "MA Crossover"):
            for sw in [max(5, int(round(x))) for x in pct_grid(float(base_short))]:
                for lw in [max(sw + 1, int(round(x))) for x in pct_grid(float(base_long))]:
                    if sw >= lw:
                        continue
                    try:
                        tr = float(engine.run(data, MeanReversionStrategy(sw, lw))["total_return"])
                        returns.append(tr)
                        param_results.append({"short_window": sw, "long_window": lw, "total_return": tr})
                    except Exception:
                        continue
        else:
            for lb in [max(10, int(round(x))) for x in pct_grid(float(base_lookback_period))]:
                try:
                    tr = float(engine.run(data, MomentumStrategy(lb))["total_return"])
                    returns.append(tr)
                    param_results.append({"lookback_period": lb, "total_return": tr})
                except Exception:
                    continue
    except Exception:
        pass

    if not returns:
        return {"param_results": [], "stability_score": None, "best_param": None, "worst_param": None}

    arr = np.array(returns, dtype=float)
    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr))
    stability = float(std_r / max(abs(mean_r), 1e-6))
    bi, wi = int(np.argmax(arr)), int(np.argmin(arr))
    return {
        "param_results": param_results,
        "stability_score": stability,
        "best_param": param_results[bi],
        "worst_param": param_results[wi],
    }


def bootstrap_confidence_intervals(
    equity_series: pd.Series,
    *,
    n_samples: int = 1000,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
) -> dict[str, Any]:
    """IID resample of daily returns; compound path per draw for total return and Sharpe."""
    rng = rng or np.random.default_rng()
    if equity_series is None or len(equity_series) < 10:
        return {
            "return_ci_95": [None, None],
            "sharpe_ci_95": [None, None],
            "distribution_summary": {"n": 0},
        }
    dr = daily_returns_from_equity(equity_series.astype(float)).dropna()
    if len(dr) < 10:
        return {
            "return_ci_95": [None, None],
            "sharpe_ci_95": [None, None],
            "distribution_summary": {"n": len(dr)},
        }
    n = len(dr)
    rets_out: list[float] = []
    sharpes_out: list[float] = []
    for _ in range(n_samples):
        sample = dr.iloc[rng.integers(0, n, size=n)].values
        path = INITIAL_CAPITAL * np.cumprod(1.0 + sample)
        rets_out.append(float(path[-1] / INITIAL_CAPITAL - 1.0))
        sharpes_out.append(sharpe_from_daily_returns(pd.Series(sample)))
    lo, hi = alpha / 2, 1.0 - alpha / 2
    return {
        "return_ci_95": [float(np.quantile(rets_out, lo)), float(np.quantile(rets_out, hi))],
        "sharpe_ci_95": [float(np.quantile(sharpes_out, lo)), float(np.quantile(sharpes_out, hi))],
        "distribution_summary": {
            "n_bootstrap": n_samples,
            "return_mean": float(np.mean(rets_out)),
            "return_std": float(np.std(rets_out)),
            "sharpe_mean": float(np.mean(sharpes_out)),
            "sharpe_std": float(np.std(sharpes_out)),
        },
    }


def regime_based_analysis(
    equity_series: pd.Series,
    market_prices: pd.Series,
    *,
    daily_threshold: float = 0.00025,
) -> dict[str, Any]:
    """Classify days by SPY daily return; metrics on strategy returns in each regime."""
    out: dict[str, Any] = {"regimes": {}}
    if equity_series is None or len(equity_series) < 5 or market_prices is None or len(market_prices) < 5:
        return out

    strat_dr = daily_returns_from_equity(equity_series.astype(float)).dropna()
    mkt = market_prices.astype(float)
    mkt.index = pd.to_datetime(mkt.index).normalize()
    mkt_dr = mkt.pct_change()

    def bucket(r: float) -> str:
        if r > daily_threshold:
            return "uptrend"
        if r < -daily_threshold:
            return "downtrend"
        return "sideways"

    for name in ("uptrend", "downtrend", "sideways"):
        vals: list[float] = []
        for idx in strat_dr.index:
            mr = mkt_dr.reindex([idx]).squeeze()
            mr = float(mr) if pd.notna(mr) else 0.0
            if bucket(mr) == name:
                vals.append(float(strat_dr.loc[idx]))
        if len(vals) < 2:
            out["regimes"][name] = {
                "return": None,
                "sharpe": None,
                "max_drawdown": None,
                "n_days": len(vals),
            }
            continue
        sub = pd.Series(vals)
        eq_path = INITIAL_CAPITAL * (1.0 + sub).cumprod()
        out["regimes"][name] = {
            "return": float((1.0 + sub).prod() - 1.0),
            "sharpe": float(sharpe_from_daily_returns(sub)),
            "max_drawdown": float(max_drawdown_from_equity(eq_path)),
            "n_days": len(sub),
        }
    return out


def compute_robustness_score(
    walk_forward: dict,
    param_sens: dict,
    bootstrap: dict,
    regime: dict,
    *,
    w1: float = 0.25,
    w2: float = 0.25,
    w3: float = 0.25,
    w4: float = 0.25,
) -> dict[str, Any]:
    """Weighted sum of normalized subscores; interpretation label."""

    def clip01(x: float) -> float:
        return float(max(0.0, min(1.0, x)))

    agg = walk_forward.get("aggregate") or {}
    ar, rs = agg.get("avg_return"), agg.get("return_std")
    if ar is not None and rs is not None and agg.get("n_windows", 0) >= 2:
        c1 = clip01(1.0 / (1.0 + float(rs) / max(abs(float(ar)), 1e-6)))
    else:
        c1 = 0.5

    stab = param_sens.get("stability_score")
    if stab is not None and np.isfinite(stab):
        c2 = clip01(1.0 / (1.0 + float(stab)))
    else:
        c2 = 0.5

    ci = bootstrap.get("return_ci_95") or [None, None]
    dist = bootstrap.get("distribution_summary") or {}
    mean_r = dist.get("return_mean")
    if ci[0] is not None and ci[1] is not None and mean_r is not None:
        rel = (float(ci[1]) - float(ci[0])) / max(abs(float(mean_r)), 0.02)
        c3 = clip01(1.0 - min(1.0, rel))
    else:
        c3 = 0.5

    regimes = regime.get("regimes") or {}
    rvals = [
        float((regimes.get(k) or {}).get("return"))
        for k in ("uptrend", "downtrend", "sideways")
        if (regimes.get(k) or {}).get("return") is not None
    ]
    if len(rvals) >= 2:
        c4 = clip01(
            1.0
            / (
                1.0
                + float(np.std(rvals)) / max(float(np.mean(np.abs(rvals))), 1e-6)
            )
        )
    else:
        c4 = 0.5

    score = w1 * c1 + w2 * c2 + w3 * c3 + w4 * c4
    interp = "robust" if score >= 0.65 else ("moderate" if score >= 0.35 else "fragile")
    return {
        "robustness_score": float(score),
        "interpretation": interp,
        "components": {
            "consistency_across_windows": c1,
            "parameter_stability": c2,
            "ci_tightness": c3,
            "regime_consistency": c4,
        },
        "weights": {"w1": w1, "w2": w2, "w3": w3, "w4": w4},
    }


def run_robustness_suite(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy_name: str,
    *,
    equity_series: pd.Series | None = None,
    short_window: int = 50,
    long_window: int = 200,
    lookback_period: int = 120,
    stat_lookback: int = 60,
    entry_threshold: float = 2.0,
    exit_threshold: float = 0.5,
    train_bars: int = 120,
    test_bars: int = 30,
    n_bootstrap: int = 1000,
    rng: np.random.Generator | None = None,
) -> dict[str, Any]:
    """End-to-end robustness for divergence/API."""
    from data.loader import load_data

    rng = rng or np.random.default_rng()
    sym = (ticker or "").strip().upper()
    sk = "MeanReversion" if strategy_name == "MA Crossover" else strategy_name
    is_pair = sk == "Stat Arb" and "-" in sym
    ta, tb = None, None
    if is_pair:
        parts = sym.split("-", 1)
        ta, tb = parts[0].strip(), parts[1].strip()

    try:
        if is_pair and ta and tb:
            data = load_data(ta, start_date, end_date)
            data_b = load_data(tb, start_date, end_date)
        else:
            data = load_data(sym, start_date, end_date)
            data_b = None
    except Exception as e:
        return {"skipped": True, "reason": str(e)}

    if data is None or data.empty:
        return {"skipped": True, "reason": "no_data"}

    if is_pair and data_b is not None and ta and tb:

        def factory():
            return StatArbStrategy(ta, tb, stat_lookback, entry_threshold, exit_threshold)

        wf = walk_forward_validation(
            data,
            "Stat Arb",
            train_bars=train_bars,
            test_bars=test_bars,
            data_b=data_b,
            stat_strategy_factory=factory,
        )
        ps = parameter_sensitivity(
            data,
            "Stat Arb",
            data_b=data_b,
            ticker_a=ta,
            ticker_b=tb,
            base_stat_lookback=stat_lookback,
            base_entry=entry_threshold,
            base_exit=exit_threshold,
        )
    else:
        wf = walk_forward_validation(data, sk, train_bars=train_bars, test_bars=test_bars)
        ps = parameter_sensitivity(
            data,
            sk,
            base_lookback_period=lookback_period,
            base_short=short_window,
            base_long=long_window,
        )

    eq = equity_series
    if eq is None or (hasattr(eq, "empty") and eq.empty):
        try:
            eng = BacktestEngine()
            if is_pair and data_b is not None and ta and tb:
                eq = eng.run_pair(
                    data,
                    data_b,
                    StatArbStrategy(ta, tb, stat_lookback, entry_threshold, exit_threshold),
                )["portfolio_values"]
            elif sk == "MeanReversion":
                eq = eng.run(data, MeanReversionStrategy(short_window, long_window))["portfolio_values"]
            else:
                eq = eng.run(data, MomentumStrategy(lookback_period))["portfolio_values"]
        except Exception:
            eq = pd.Series(dtype=float)

    boot = bootstrap_confidence_intervals(eq, n_samples=n_bootstrap, rng=rng)
    try:
        spy = load_data("SPY", start_date, end_date)["Close"].astype(float)
        spy.index = pd.to_datetime(spy.index).normalize()
    except Exception:
        spy = pd.Series(dtype=float)

    reg = regime_based_analysis(eq if eq is not None else pd.Series(dtype=float), spy)
    detail = compute_robustness_score(wf, ps, boot, reg)

    return {
        "walk_forward": wf,
        "parameter_sensitivity": ps,
        "bootstrap": boot,
        "regime_analysis": reg,
        "robustness_score": detail["robustness_score"],
        "interpretation": detail["interpretation"],
        "robustness_detail": detail,
        "skipped": False,
    }
