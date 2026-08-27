"""
Backtest vs live divergence: align equity curves, compare metrics, simple attribution, rolling gaps.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.benchmark import metrics_from_equity_series
from engine.backtest_engine import BacktestEngine
from trading_constants import DEFAULT_COMMISSION, INITIAL_CAPITAL


def _parse_date(s: str) -> pd.Timestamp:
    return pd.Timestamp(str(s)[:10])


def load_backtest_equity_series(result_row: dict) -> pd.Series:
    """Parse equity_curve from get_backtest_results row into a daily Series."""
    curve = result_row.get("equity_curve") or []
    if not curve:
        return pd.Series(dtype=float)
    dates = []
    vals = []
    for pt in curve:
        ts = pt.get("timestamp") or pt.get("date")
        if ts is None:
            continue
        dates.append(_parse_date(str(ts)))
        vals.append(float(pt["portfolio_value"]))
    if not dates:
        return pd.Series(dtype=float)
    s = pd.Series(vals, index=pd.DatetimeIndex(dates))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.astype(float)


def _strategy_aliases(name: str) -> set[str]:
    """
    Every spelling a stored row might use for this strategy.

    Live trades are keyed "MA Crossover"; backtest rows written before the
    rename are keyed "MeanReversion". Matching one and not the other silently
    drops half the history being compared.
    """
    from strategies.naming import storage_aliases
    return {(name or "").strip(), *storage_aliases(name)}


def load_live_equity_series(
    history_rows: list,
    strategy: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.Series:
    """
    Build Series from portfolio_snapshots rows (raw DB tuples).
    Each row: (id, timestamp, strategy, portfolio_value, cash, positions).
    """
    start_ts = _parse_date(start) if start else None
    end_ts = _parse_date(end) if end else None
    accepted = _strategy_aliases(strategy) if strategy else set()
    dates = []
    vals = []
    for snap in history_rows:
        if len(snap) < 4:
            continue
        if accepted and snap[2] not in accepted:
            continue
        ts_raw = snap[1] or ""
        d = _parse_date(str(ts_raw))
        if start_ts is not None and d.normalize() < start_ts.normalize():
            continue
        if end_ts is not None and d.normalize() > end_ts.normalize():
            continue
        dates.append(d.normalize())
        vals.append(float(snap[3]))
    if not dates:
        return pd.Series(dtype=float)
    s = pd.Series(vals, index=pd.DatetimeIndex(dates))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.astype(float)


def align_and_rebase(
    bt: pd.Series,
    live: pd.Series,
    start: str | None = None,
    end: str | None = None,
    forward_fill_live: bool = False,
) -> tuple[pd.Series, pd.Series, dict]:
    """
    Intersect date range, optionally clip [start,end], rebase both to INITIAL_CAPITAL at first common date.
    Default: inner join on dates only (no invented live points).
    """
    meta: dict[str, Any] = {"mode": "inner_join"}
    if bt.empty or live.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float), {**meta, "error": "empty_series"}

    bt = bt.copy()
    live = live.copy()
    bt.index = pd.DatetimeIndex(bt.index).normalize()
    live.index = pd.DatetimeIndex(live.index).normalize()

    if start:
        t0 = _parse_date(start).normalize()
        bt = bt[bt.index >= t0]
        live = live[live.index >= t0]
    if end:
        t1 = _parse_date(end).normalize()
        bt = bt[bt.index <= t1]
        live = live[live.index <= t1]

    common = bt.index.intersection(live.index)
    if len(common) == 0:
        if forward_fill_live:
            meta["mode"] = "ffill_live_to_bt_index"
            aligned = pd.DataFrame({"bt": bt}).join(
                pd.DataFrame({"live": live}).reindex(bt.index).ffill(),
                how="inner",
            )
            aligned = aligned.dropna(subset=["live"])
            if aligned.empty:
                return pd.Series(dtype=float), pd.Series(dtype=float), {**meta, "error": "no_overlap"}
            bt_a = aligned["bt"].astype(float)
            live_a = aligned["live"].astype(float)
        else:
            return pd.Series(dtype=float), pd.Series(dtype=float), {**meta, "error": "no_overlap"}
    else:
        bt_a = bt.loc[common].astype(float)
        live_a = live.loc[common].astype(float)

    b0 = float(bt_a.iloc[0])
    l0 = float(live_a.iloc[0])
    if b0 <= 0 or l0 <= 0:
        return pd.Series(dtype=float), pd.Series(dtype=float), {**meta, "error": "non_positive_start"}

    scale_bt = INITIAL_CAPITAL / b0
    scale_live = INITIAL_CAPITAL / l0
    bt_rb = bt_a * scale_bt
    live_rb = live_a * scale_live

    meta.update(
        {
            "first_date": str(bt_rb.index[0].date()),
            "last_date": str(bt_rb.index[-1].date()),
            "n_points": int(len(bt_rb)),
        }
    )
    return bt_rb, live_rb, meta


def _metrics_triplet(m: dict) -> dict:
    return {
        "return": float(m.get("total_return", 0.0)),
        "sharpe": float(m.get("sharpe_ratio", 0.0)),
        "max_drawdown": float(m.get("max_drawdown", 0.0)),
    }


def compare_metrics(bt_series: pd.Series, live_series: pd.Series, initial_capital: float) -> tuple[dict, dict, dict]:
    """Compute backtest, live, and delta metric dicts (return/sharpe/max_drawdown keys)."""
    if bt_series.empty or live_series.empty or len(bt_series) < 2:
        z = {"return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
        return z.copy(), z.copy(), z.copy()

    bt_m = metrics_from_equity_series(bt_series, initial_capital)
    live_m = metrics_from_equity_series(live_series, initial_capital)

    bt_out = _metrics_triplet(bt_m)
    live_out = _metrics_triplet(live_m)
    delta = {
        "return": live_out["return"] - bt_out["return"],
        "sharpe": live_out["sharpe"] - bt_out["sharpe"],
        "max_drawdown": live_out["max_drawdown"] - bt_out["max_drawdown"],
    }
    return bt_out, live_out, delta


def build_strategy_for_divergence(
    strategy_name: str,
    short_window: int = 50,
    long_window: int = 200,
    lookback_period: int = 120,
    ticker_a: str | None = None,
    ticker_b: str | None = None,
    lookback: int = 60,
    entry_threshold: float = 2.0,
    exit_threshold: float = 0.5,
):
    """Mirror live/api._build_strategy without importing api (avoid circular imports)."""
    from strategies.ma_crossover import MACrossoverStrategy
    from strategies.momentum import MomentumStrategy
    from strategies.naming import MA_CROSSOVER, STAT_ARB, canonical
    from strategies.stat_arb import StatArbStrategy

    if canonical(strategy_name) == STAT_ARB and ticker_a and ticker_b:
        return StatArbStrategy(
            ticker_a=ticker_a,
            ticker_b=ticker_b,
            lookback=lookback,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
        )
    if canonical(strategy_name) == MA_CROSSOVER:
        return MACrossoverStrategy(short_window=short_window, long_window=long_window)
    return MomentumStrategy(lookback_period=lookback_period)


def _run_same_bar_close_fill(data: pd.DataFrame, strategy, engine_params: dict) -> float:
    """
    Legacy-style simulation: signal at bar i uses Close[i]; fill at Close[i] same bar.
    Positive estimated_return_delta vs proper engine means this path overstates edge.
    """
    signals = strategy.generate_signals(data)
    closes = data["Close"].astype(float)
    cash = float(engine_params.get("initial_capital", INITIAL_CAPITAL))
    commission = float(engine_params.get("commission", DEFAULT_COMMISSION))
    max_dollar = float(engine_params.get("max_dollar_per_stock", engine_params.get("max_dollar", 10_000)))
    bp = float(engine_params.get("buying_power_fraction", 0.95))
    shares = 0

    for i in range(len(data)):
        if i == 0:
            continue
        px = float(closes.iloc[i])
        raw_sig = signals.iloc[i]
        sig = int(raw_sig) if pd.notna(raw_sig) else 0
        if sig == 1 and shares == 0 and px > 0:
            dollar = min(max_dollar, cash * bp)
            qty = int(dollar / px)
            if qty > 0:
                cash -= qty * px * (1.0 + commission)
                shares = qty
        elif sig == 0 and shares > 0 and px > 0:
            cash += shares * px * (1.0 - commission)
            shares = 0

    final = cash + shares * float(closes.iloc[-1])
    return (final / float(engine_params.get("initial_capital", INITIAL_CAPITAL))) - 1.0


def estimate_execution_timing_impact(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy_name: str,
    *,
    short_window: int = 50,
    long_window: int = 200,
    lookback_period: int = 120,
) -> dict[str, Any]:
    """Compare same-bar close fills vs T+1 open fills (single-name strategies only)."""
    if strategy_name == "Stat Arb":
        return {
            "estimated_return_delta": None,
            "skipped": True,
            "reason": "Stat Arb timing decomposition not implemented in v1",
        }
    from data.loader import load_data

    data = load_data(ticker, start_date, end_date)
    if data is None or data.empty or len(data) < 3:
        return {"estimated_return_delta": None, "skipped": True, "reason": "no_ohlc_data"}

    strategy = build_strategy_for_divergence(
        strategy_name,
        short_window=short_window,
        long_window=long_window,
        lookback_period=lookback_period,
    )
    engine = BacktestEngine()
    proper = engine.run(data, strategy)["total_return"]
    same_bar = _run_same_bar_close_fill(
        data,
        strategy,
        {
            "initial_capital": engine.initial_capital,
            "commission": engine.commission,
            "max_dollar_per_stock": engine.max_dollar_per_stock,
            "buying_power_fraction": engine.buying_power_fraction,
        },
    )
    return {
        "estimated_return_delta": float(same_bar - proper),
        "return_same_bar_close_model": float(same_bar),
        "return_next_open_model": float(proper),
        "skipped": False,
    }


def estimate_transaction_cost_impact(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy_name: str,
    *,
    short_window: int = 50,
    long_window: int = 200,
    lookback_period: int = 120,
) -> dict[str, Any]:
    """Return difference total_return(commission=0) - total_return(default commission)."""
    if strategy_name == "Stat Arb":
        return {"estimated_return_delta": None, "skipped": True, "reason": "Stat Arb not in v1"}

    from data.loader import load_data

    data = load_data(ticker, start_date, end_date)
    if data is None or data.empty:
        return {"estimated_return_delta": None, "skipped": True, "reason": "no_ohlc_data"}

    strategy = build_strategy_for_divergence(
        strategy_name,
        short_window=short_window,
        long_window=long_window,
        lookback_period=lookback_period,
    )
    z = BacktestEngine(commission=0.0).run(data, strategy)["total_return"]
    c = BacktestEngine(commission=DEFAULT_COMMISSION).run(data, strategy)["total_return"]
    return {
        "estimated_return_delta": float(z - c),
        "return_zero_commission": float(z),
        "return_default_commission": float(c),
        "skipped": False,
    }


def estimate_data_source_impact(
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Yahoo vs Alpaca daily close return mismatch (vendor noise), when Alpaca is available."""
    from data.loader import load_data

    ydf = load_data(ticker, start_date, end_date)
    if ydf is None or ydf.empty or "Close" not in ydf.columns:
        return {"skipped": True, "reason": "no_yahoo_data"}

    y = ydf["Close"].astype(float)
    y.index = pd.to_datetime(y.index).normalize()
    y_ret = np.log(y / y.shift(1)).dropna()

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        return {
            "skipped": True,
            "reason": "no_alpaca_keys",
            "mean_abs_log_return_diff": None,
            "correlation": None,
        }

    try:
        from alpaca.data.enums import Adjustment
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        return {"skipped": True, "reason": "alpaca_sdk_missing"}

    try:
        client = StockHistoricalDataClient(api_key, secret_key)
        end_dt = datetime.strptime(end_date[:10], "%Y-%m-%d") + timedelta(days=1)
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=datetime.strptime(start_date[:10], "%Y-%m-%d"),
            end=end_dt,
            adjustment=Adjustment.ALL,
        )
        bars = client.get_stock_bars(req)
        df = getattr(bars, "df", pd.DataFrame())
        if df.empty:
            return {"skipped": True, "reason": "alpaca_empty_bars"}

        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        ts_col = "timestamp" if "timestamp" in df.columns else None
        if ts_col is None or "close" not in df.columns:
            return {"skipped": True, "reason": "alpaca_unexpected_shape"}
        ac = (
            df.set_index(pd.to_datetime(df[ts_col]))["close"]
            .astype(float)
            .sort_index()
        )
        ac.index = pd.DatetimeIndex(ac.index).normalize()
        ac = ac[~ac.index.duplicated(keep="last")]
        a_ret = np.log(ac / ac.shift(1)).dropna()

        common = y_ret.index.intersection(a_ret.index)
        if len(common) < 5:
            return {"skipped": True, "reason": "insufficient_overlap", "overlap_days": int(len(common))}

        yc = y_ret.loc[common]
        ac2 = a_ret.loc[common]
        diff = (yc - ac2).abs()
        corr = float(yc.corr(ac2)) if yc.std() > 0 and ac2.std() > 0 else None
        return {
            "skipped": False,
            "mean_abs_log_return_diff": float(diff.mean()),
            "correlation": corr,
            "overlap_days": int(len(common)),
        }
    except Exception as e:
        return {"skipped": True, "reason": f"alpaca_error:{e!s}"}


def rolling_performance_gaps(
    bt: pd.Series,
    live: pd.Series,
    windows: tuple[int, ...] = (7, 14),
    top_n: int = 5,
) -> dict[str, Any]:
    """Trailing w trading-day return on rebased levels; delta_return = live - backtest."""
    out: dict[str, Any] = {}
    if bt.empty or live.empty:
        for w in windows:
            out[f"window_{w}d"] = []
        out["largest_divergence_periods"] = []
        return out

    aligned = pd.DataFrame({"bt": bt.astype(float), "live": live.astype(float)}).dropna()
    if len(aligned) <= max(windows):
        for w in windows:
            out[f"window_{w}d"] = []
        out["largest_divergence_periods"] = []
        return out

    idx = aligned.index
    largest_all: list[dict] = []

    for w in windows:
        bt_r = aligned["bt"] / aligned["bt"].shift(w) - 1.0
        lv_r = aligned["live"] / aligned["live"].shift(w) - 1.0
        dlt = lv_r - bt_r
        fixed: list[dict] = []
        for end_pos in range(w, len(aligned)):
            if pd.isna(bt_r.iloc[end_pos]):
                continue
            end_idx = idx[end_pos]
            start_idx = idx[end_pos - w]
            fixed.append(
                {
                    "start_date": str(start_idx.date()),
                    "end_date": str(end_idx.date()),
                    "delta_return": float(dlt.iloc[end_pos]),
                    "backtest_return": float(bt_r.iloc[end_pos]),
                    "live_return": float(lv_r.iloc[end_pos]),
                }
            )
        out[f"window_{w}d"] = fixed
        for r in fixed:
            largest_all.append({**r, "window": w})

    largest_all.sort(key=lambda x: abs(x["delta_return"]), reverse=True)
    out["largest_divergence_periods"] = largest_all[:top_n]
    return out


def build_full_report(
    backtest_row: dict,
    history_rows: list,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    forward_fill_live: bool = False,
    short_window: int = 50,
    long_window: int = 200,
    lookback_period: int = 120,
    stat_lookback: int = 60,
    entry_threshold: float = 2.0,
    exit_threshold: float = 0.5,
    include_robustness: bool = True,
    n_bootstrap: int = 1000,
) -> dict[str, Any]:
    """Assemble comparison, attribution, rolling, optional robustness suite, warnings."""
    warnings = [
        "Live portfolio_value snapshots are account-level; multi-ticker runs mix P&L vs single-name backtests.",
    ]

    strat = backtest_row.get("strategy") or "Momentum"
    ticker = (backtest_row.get("ticker") or "").strip().upper()
    bt_start = start_date or backtest_row.get("start_date")
    bt_end = end_date or backtest_row.get("end_date")

    bt_series = load_backtest_equity_series(backtest_row)
    live_series = load_live_equity_series(history_rows, strat, bt_start, bt_end)

    bt_a, live_a, align_meta = align_and_rebase(
        bt_series, live_series, bt_start, bt_end, forward_fill_live=forward_fill_live
    )

    if "error" in align_meta:
        warnings.append(f"Alignment failed: {align_meta['error']}")

    bt_m, live_m, delta_m = compare_metrics(bt_a, live_a, INITIAL_CAPITAL)

    timing = estimate_execution_timing_impact(
        ticker.split("-")[0] if ticker else "",
        str(bt_start),
        str(bt_end),
        strat,
        short_window=short_window,
        long_window=long_window,
        lookback_period=lookback_period,
    )
    costs = estimate_transaction_cost_impact(
        ticker.split("-")[0] if ticker else "",
        str(bt_start),
        str(bt_end),
        strat,
        short_window=short_window,
        long_window=long_window,
        lookback_period=lookback_period,
    )
    data_impact = estimate_data_source_impact(
        ticker.split("-")[0] if ticker else "",
        str(bt_start),
        str(bt_end),
    )

    rolling = rolling_performance_gaps(bt_a, live_a, windows=(7, 14), top_n=5)

    robustness: dict[str, Any] = {"skipped": True, "reason": "disabled"}
    if include_robustness and bt_start and bt_end:
        try:
            from analytics.robustness import run_robustness_suite

            sym_ticker = ticker if strat == "Stat Arb" else (ticker.split("-")[0] if ticker else "")
            eq_for_boot = (
                bt_series
                if bt_series is not None and not bt_series.empty and len(bt_series) >= 10
                else None
            )
            robustness = run_robustness_suite(
                sym_ticker,
                str(bt_start),
                str(bt_end),
                strat,
                equity_series=eq_for_boot,
                short_window=short_window,
                long_window=long_window,
                lookback_period=lookback_period,
                stat_lookback=stat_lookback,
                entry_threshold=entry_threshold,
                exit_threshold=exit_threshold,
                n_bootstrap=n_bootstrap,
            )
        except Exception as e:
            robustness = {"skipped": True, "reason": str(e)}

    return {
        "backtest": bt_m,
        "live": live_m,
        "delta": delta_m,
        "attribution": {
            "execution_timing_impact": timing,
            "transaction_cost_impact": costs,
            "data_source_impact": data_impact,
            "rolling": rolling,
        },
        "robustness": robustness,
        "warnings": warnings,
        "window": align_meta,
    }
