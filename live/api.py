"""
FastAPI backend for live trading dashboard.
"""

import sys
import os
LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

import logging
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import Database

logger = logging.getLogger(__name__)
from pairs_config import get_available_pairs, is_valid_pair
import json
from datetime import datetime, timezone, timedelta, date
import pandas as pd
from dotenv import load_dotenv
load_dotenv(os.path.join(LIVE_DIR, ".env"))

app = FastAPI()

# CORS. Set ALLOWED_ORIGINS to a comma-separated list of your frontend origins
# in production, e.g. "https://backtrace.vercel.app". Defaults to "*" so local
# development and the existing deployment keep working.
#
# allow_credentials is False whenever origins is "*": that combination is
# invalid per the CORS spec and browsers reject the response, so the previous
# allow_origins=["*"] with allow_credentials=True was not doing what it looked
# like it was doing.
_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Write-side authentication.
#
# Two endpoints change state outside this process: POST /run-executor submits
# real orders to Alpaca, and DELETE /trades/{id} destroys audit records. Both
# were reachable by anyone who knew the URL, on a service the README tells you
# to deploy publicly.
#
# Default-deny: unless BACKTRACE_API_KEY is set in the environment, they return
# 503 and do nothing. When it is set, callers must send a matching X-API-Key.
# Read-only GETs stay open so the dashboard keeps working unchanged.
#
# Note this intentionally disables the dashboard's "Run Strategy" button in a
# public deployment. A browser button cannot hold a secret - shipping the key in
# the frontend bundle would publish it - so an unauthenticated public button
# that places brokerage orders cannot be made safe while staying a public
# button. The scheduler places the real trades on its own; manual runs are a
# convenience, available via curl with the key or by running locally.
API_KEY = os.getenv("BACKTRACE_API_KEY", "").strip()


def require_write_auth(x_api_key: str = Header(default=None, alias="X-API-Key")):
    """Gate for endpoints that place orders or delete records."""
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "Write endpoints are disabled. Set BACKTRACE_API_KEY in the server "
                "environment to enable them, then send it as the X-API-Key header."
            ),
        )
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header.")
    return True

DB_PATH = os.getenv("DB_PATH") or os.path.join(LIVE_DIR, "trading.db")
db = Database(DB_PATH)

# Max equity curve points returned to frontend to avoid OOM / DataCloneError
EQUITY_CURVE_MAX_POINTS = 400


def _downsample_equity_curve(equity_curve: list, max_points: int = EQUITY_CURVE_MAX_POINTS) -> list:
    """Return a downsampled copy of equity_curve with at most max_points, evenly spaced. Keeps first and last."""
    if not equity_curve or len(equity_curve) <= max_points:
        return equity_curve
    n = len(equity_curve)
    step = (n - 1) / (max_points - 1)
    indices = [0] + [int(round(i * step)) for i in range(1, max_points - 1)] + [n - 1]
    return [equity_curve[i] for i in indices]


@app.get("/")
def read_root():
    return {"message": "BackTrace Live API"}


def _get_portfolio_from_alpaca():
    """Fetch live portfolio from Alpaca. Returns dict or None on failure."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        logger.warning("Alpaca keys missing in API process; portfolio will use DB fallback.")
        return None
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=True)
        account = client.get_account()
        positions = client.get_all_positions()
        positions_dict = {}
        for pos in positions:
            try:
                qty = float(pos.qty or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty != 0 and getattr(pos, "symbol", None):
                positions_dict[pos.symbol] = qty
        return {
            "portfolio_value": float(account.portfolio_value or 0),
            "cash": float(account.cash or 0),
            "positions": positions_dict,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": None,
        }
    except Exception as e:
        logger.exception("Alpaca portfolio fetch failed: %s", e)
        return None


@app.get("/portfolio")
def get_portfolio():
    """Current portfolio: live from Alpaca when available, else latest DB snapshot."""
    live = _get_portfolio_from_alpaca()
    if live is not None:
        # Use strategy from latest DB snapshot if we have one
        history = db.get_portfolio_history()
        if history:
            live["strategy"] = history[-1][2]
        if live["strategy"] is None:
            live["strategy"] = "Live"
        live["live_sync_used"] = True
        return live

    # Fallback: latest snapshot from DB (check server logs for "Alpaca portfolio fetch failed" if live expected)
    history = db.get_portfolio_history()
    if not history:
        return {
            "portfolio_value": 0,
            "cash": 0,
            "positions": {},
            "timestamp": None,
            "strategy": None,
            "live_sync_used": False,
        }
    latest = history[-1]
    positions_raw = latest[5]
    positions = json.loads(positions_raw) if positions_raw else {}
    return {
        "portfolio_value": float(latest[3]),
        "cash": float(latest[4]),
        "positions": positions,
        "timestamp": latest[1],
        "strategy": latest[2],
        "live_sync_used": False,
    }


@app.get("/positions-detail")
def get_positions_detail():
    """
    Live position details from Alpaca: entry price, current price, P&L, P&L%.
    For Current Portfolio tab. Returns empty positions if Alpaca keys missing or error.
    """
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        return {
            "portfolio_value": 0,
            "cash": 0,
            "positions": [],
            "timestamp": None,
        }
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=True)
        account = client.get_account()
        positions = client.get_all_positions()
        out = []
        for pos in positions:
            qty = float(pos.qty)
            if qty == 0:
                continue
            entry_price = float(pos.avg_entry_price or 0) if hasattr(pos, "avg_entry_price") else (float(pos.cost_basis or 0) / abs(qty) if qty else 0)
            current_price = float(pos.current_price or 0) if hasattr(pos, "current_price") else (float(pos.market_value or 0) / abs(qty) if qty else 0)
            unrealized_pl = float(pos.unrealized_pl or 0) if hasattr(pos, "unrealized_pl") else (current_price - entry_price) * qty
            cost_basis = float(pos.cost_basis or 0) or (entry_price * abs(qty))
            unrealized_plpc = float(pos.unrealized_plpc or 0) if hasattr(pos, "unrealized_plpc") else (unrealized_pl / cost_basis if cost_basis else 0)
            out.append({
                "symbol": pos.symbol,
                "qty": qty,
                "entry_price": entry_price,
                "current_price": current_price,
                "pnl": unrealized_pl,
                "pnl_pct": unrealized_plpc,
            })
        return {
            "portfolio_value": float(account.portfolio_value or 0),
            "cash": float(account.cash or 0),
            "positions": out,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "portfolio_value": 0,
            "cash": 0,
            "positions": [],
            "timestamp": None,
            "error": str(e),
        }


@app.get("/trades")
def get_trades(strategy: str = None):
    """Get all trades, optionally filtered by strategy. Each trade includes params if stored."""
    trades = db.get_all_trades(strategy=strategy)
    return {"trades": trades}


@app.get("/execution-logs")
def get_execution_logs(strategy: str = None, ticker: str = None, limit: int = 200):
    """Get execution decision logs with optional strategy/ticker filters."""
    safe_limit = max(1, min(limit, 1000))
    logs = db.get_execution_logs(strategy=strategy, ticker=ticker, limit=safe_limit)
    return {"execution_logs": logs}


@app.get("/available-pairs/{ticker}")
def get_pairs_for_ticker(ticker: str):
    """Get list of valid pairs for a ticker."""
    pairs = get_available_pairs(ticker.upper())
    return {"ticker": ticker.upper(), "available_pairs": pairs}


@app.get("/pairs")
def get_pairs(strategy: str = "Stat Arb"):
    """Get current pair positions for stat arb. Uses latest portfolio snapshot + last known pair."""
    history = db.get_portfolio_history(strategy=strategy)
    pair_trades = db.get_pair_trades(strategy=strategy)
    if not history:
        return {"pairs": []}
    latest = history[-1]
    positions = json.loads(latest[5]) if latest[5] else {}
    portfolio_value = latest[3]
    pairs_out = []
    if pair_trades:
        # Use most recent pair_trade to know which pair we're tracking
        pt = pair_trades[0]
        ticker_a, ticker_b = pt["ticker_a"], pt["ticker_b"]
        pair_name = pt["pair_name"]
        qty_a = positions.get(ticker_a, 0)
        qty_b = positions.get(ticker_b, 0)
        if qty_a != 0 or qty_b != 0:
            pairs_out.append({
                "pair_name": pair_name,
                "ticker_a": ticker_a,
                "ticker_b": ticker_b,
                "qty_a": qty_a,
                "qty_b": qty_b,
                "combined_value": portfolio_value,
            })
    return {"pairs": pairs_out}


@app.get("/pair-trades")
def get_pair_trades(strategy: str = None):
    """Get pair trades from database, optionally filtered by strategy."""
    trades = db.get_pair_trades(strategy=strategy)
    return {"pair_trades": trades}


@app.delete("/trades/{trade_id}")
def delete_trade(trade_id: int, _auth: bool = Depends(require_write_auth)):
    """Delete a trade by id. Requires X-API-Key; destroys an audit record."""
    if not db.delete_trade(trade_id):
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"ok": True}


@app.get("/portfolio-history")
def get_portfolio_history_endpoint(strategy: str = None):
    """Get portfolio value over time."""
    history = db.get_portfolio_history(strategy=strategy)
    
    history_list = []
    for snapshot in history:
        positions_raw = snapshot[5]
        try:
            positions = json.loads(positions_raw) if positions_raw else {}
        except (TypeError, json.JSONDecodeError):
            positions = {}
        history_list.append({
            "timestamp": snapshot[1],
            "strategy": snapshot[2],
            "portfolio_value": snapshot[3],
            "cash": snapshot[4],
            "positions": positions,
        })
    
    return {"history": history_list}


DAILY_BARS_MAX_POINTS = 500


def _time_range_to_dates(time_range: str) -> tuple[str, str]:
    """Return (start_date, end_date) as YYYY-MM-DD, inclusive end."""
    end = datetime.now(timezone.utc).date()
    tr = (time_range or "1Y").strip().upper()
    if tr == "1M":
        start = end - timedelta(days=32)
    elif tr == "3M":
        start = end - timedelta(days=95)
    elif tr == "6M":
        start = end - timedelta(days=186)
    elif tr == "1Y":
        start = end - timedelta(days=370)
    elif tr == "ALL":
        start = end - timedelta(days=365 * 12)
    else:
        start = end - timedelta(days=370)
    return start.isoformat(), end.isoformat()


def _downsample_bars(rows: list, max_points: int = DAILY_BARS_MAX_POINTS) -> list:
    if not rows or len(rows) <= max_points:
        return rows
    n = len(rows)
    step = (n - 1) / (max_points - 1)
    indices = [0] + [int(round(i * step)) for i in range(1, max_points - 1)] + [n - 1]
    return [rows[i] for i in indices]


@app.get("/daily-bars")
def get_daily_bars(ticker: str, time_range: str = "1Y"):
    """Daily OHLCV for candlestick charts. Uses cached Yahoo data via data.loader."""
    sym = (ticker or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="ticker is required")
    start_date, end_inclusive = _time_range_to_dates(time_range)
    # yfinance `end` is exclusive
    end_exclusive = (date.fromisoformat(end_inclusive) + timedelta(days=1)).isoformat()
    old_cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        from data.loader import load_data
        df = load_data(sym, start_date, end_exclusive)
    finally:
        os.chdir(old_cwd)
    if df is None or len(df) == 0:
        return {"ticker": sym, "bars": []}
    colmap = {str(c).lower(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n.lower() in colmap:
                return colmap[n.lower()]
        return None

    ocol = pick("Open")
    hcol = pick("High")
    lcol = pick("Low")
    ccol = pick("Close")
    vcol = pick("Volume")
    if not all([ocol, hcol, lcol, ccol]):
        raise HTTPException(status_code=422, detail="OHLC columns missing in market data")
    rows = []
    for idx, row in df.iterrows():
        try:
            if hasattr(idx, "strftime"):
                d = idx.strftime("%Y-%m-%d")
            else:
                d = str(idx)[:10]
            o, h, l, c = float(row[ocol]), float(row[hcol]), float(row[lcol]), float(row[ccol])
            if any(pd.isna(x) for x in (o, h, l, c)):
                continue
            vol = None
            if vcol is not None and pd.notna(row.get(vcol, float("nan"))):
                try:
                    vol = float(row[vcol])
                except (TypeError, ValueError):
                    vol = None
            rows.append(
                {
                    "date": d,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": vol,
                }
            )
        except (TypeError, ValueError, KeyError):
            continue
    rows.sort(key=lambda x: x["date"])
    rows = _downsample_bars(rows)
    return {"ticker": sym, "bars": rows}


from trading_constants import INITIAL_CAPITAL
from engine.fingerprint import backtest_fingerprint
from strategies.naming import canonical as strategy_canonical, storage_aliases
from snapshot_health import clean_series


def _compute_spy_benchmark(start_date: str, end_date: str, initial_capital: float):
    """
    SPY buy-and-hold over [start_date, end_date] with same initial capital as the strategy backtest.
    Returns a JSON-serializable dict or None if data unavailable.
    """
    old = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        from data.loader import load_data
        from analytics.benchmark import equity_series_to_curve_list, metrics_from_equity_series

        spy_df = load_data("SPY", start_date, end_date)
        if spy_df is None or len(spy_df) == 0:
            return None
        engine = _benchmark_engine(initial_capital)
        spy_results = engine.run_buyhold(spy_df)
        spy_pv = spy_results["portfolio_values"]
        m = metrics_from_equity_series(spy_pv, initial_capital)
        curve = equity_series_to_curve_list(spy_pv)
        return {
            "symbol": "SPY",
            "equity_curve": _downsample_equity_curve(curve),
            "total_return": m["total_return"],
            "sharpe_ratio": m["sharpe_ratio"],
            "max_drawdown": m["max_drawdown"],
            "daily_returns": m["daily_returns"],
        }
    except Exception as e:
        logger.warning("SPY benchmark failed: %s", e)
        return None
    finally:
        os.chdir(old)


def _benchmark_engine(initial_capital: float):
    """
    Engine configured for an index benchmark: deploy the whole account.

    The strategy engine caps each position at MAX_DOLLAR_PER_STOCK and holds back
    1 - CAPITAL_FRACTION in cash. Those are risk limits on a strategy, not
    properties of "what if I had just bought the index," but run_buyhold read the
    same settings - so the SPY benchmark was buying $10,000 of SPY and leaving
    $90,000 in cash. That reported SPY at roughly +36% over a stretch where it
    actually returned several hundred percent, and made the strategy look
    competitive with an index it was not competing with.

    A strategy that leaves most of its capital idle SHOULD underperform a fully
    invested index. That gap is a real result, so the benchmark deploys fully.
    """
    from engine.backtest_engine import BacktestEngine

    return BacktestEngine(
        initial_capital=initial_capital,
        max_dollar_per_stock=float("inf"),
        capital_fraction=1.0,
    )


def _spy_payload_for_live_window(start_date: str, end_inclusive: str):
    """
    SPY buy-and-hold over exactly [start_date, end_inclusive].
    end_inclusive is the last calendar day (inclusive); yfinance end is exclusive.
    """
    end_exclusive = (date.fromisoformat(end_inclusive) + timedelta(days=1)).isoformat()
    old = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        from data.loader import load_data
        from analytics.benchmark import equity_series_to_curve_list, metrics_from_equity_series

        spy_df = load_data("SPY", start_date, end_exclusive)
        if spy_df is None or len(spy_df) == 0:
            return None
        engine = _benchmark_engine(INITIAL_CAPITAL)
        spy_results = engine.run_buyhold(spy_df)
        spy_pv = spy_results["portfolio_values"]
        sm = metrics_from_equity_series(spy_pv, INITIAL_CAPITAL)
        spy_curve_full = equity_series_to_curve_list(spy_pv)
        return {
            "symbol": "SPY",
            "total_return": sm["total_return"],
            "sharpe_ratio": sm["sharpe_ratio"],
            "max_drawdown": sm["max_drawdown"],
            "daily_returns": sm["daily_returns"],
            "equity_curve": _downsample_equity_curve(spy_curve_full),
        }
    finally:
        os.chdir(old)


@app.get("/performance")
def get_performance(strategy: str = None):
    """
    Performance over the recorded window.

    total_return is measured from the FIRST recorded snapshot, not from the
    configured INITIAL_CAPITAL. Those differ: snapshotting began after trading
    had already started, so the first recorded value was ~103.6k rather than
    100k, and measuring against the constant silently credited the strategy with
    gains from before the record exists.

    configured_initial_capital and return_vs_configured_capital keep the old
    number available, clearly labelled as what it is.
    """
    history = db.get_portfolio_history(strategy=strategy)
    trades = db.get_all_trades(strategy=strategy)

    if not history:
        return {
            "total_return": 0.0,
            "num_trades": len(trades),
            "current_value": INITIAL_CAPITAL,
            "initial_value": INITIAL_CAPITAL,
            "configured_initial_capital": INITIAL_CAPITAL,
            "return_vs_configured_capital": 0.0,
            "first_snapshot": None,
            "last_snapshot": None,
            "snapshot_days": 0,
        }

    first_value = float(history[0][3])
    current_value = float(history[-1][3])
    baseline = first_value if first_value > 0 else INITIAL_CAPITAL

    return {
        "total_return": (current_value - baseline) / baseline,
        "num_trades": len(trades),
        "current_value": current_value,
        "initial_value": first_value,
        "configured_initial_capital": INITIAL_CAPITAL,
        "return_vs_configured_capital": (current_value - INITIAL_CAPITAL) / INITIAL_CAPITAL,
        "first_snapshot": history[0][1],
        "last_snapshot": history[-1][1],
        "snapshot_days": len({(row[1] or "")[:10] for row in history if row[1]}),
    }


def _normalize_strategy_for_db(strategy: str) -> str:
    """
    Canonical strategy name for a request.

    Kept as a thin wrapper so the endpoints read the same as before; the
    mapping itself now lives in strategies/naming.py rather than being
    reimplemented at each call site. Reads should query with
    naming.storage_aliases() so pre-rename "MeanReversion" rows stay visible.
    """
    return strategy_canonical(strategy)


def _describe_backtest(row: dict) -> dict:
    """Enough of a saved run to tell two of them apart in an error message."""
    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "code_fingerprint": row.get("code_fingerprint"),
        "total_return": row.get("total_return"),
        "num_trades": row.get("num_trades"),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
    }


def _select_backtest(results: list, backtest_id: Optional[int], ticker: str, strat_db: str):
    """
    Pick which saved backtest the live curve is compared against.

    This used to be results[0] - whichever row happened to sort first. The
    production database holds 27 runs of Momentum/AAPL over the same window
    reporting three different total returns (+29.65% and +3.84%, all at n=49),
    because the sizing code changed between them and nothing recorded which
    version produced which row. An arbitrary row was therefore setting the
    magnitude of the project's headline number.

    Now: an explicit backtest_id always wins (the caller said which one), but
    the response reports whether that run's code fingerprint still matches the
    engine running now. Without an explicit id, only runs produced by the
    current code are eligible, newest first; if none are, the endpoint refuses
    and names the stale candidates rather than quietly comparing against code
    that no longer exists.
    """
    current_fp = backtest_fingerprint()

    if backtest_id is not None:
        for r in results:
            if r.get("id") == backtest_id:
                return r, {
                    "backtest_id_used": r.get("id"),
                    "selected_by": "explicit_backtest_id",
                    "current_code_fingerprint": current_fp,
                    "backtest_code_fingerprint": r.get("code_fingerprint"),
                    "code_fingerprint_match": r.get("code_fingerprint") == current_fp,
                }
        raise HTTPException(
            status_code=422,
            detail=f"backtest_id={backtest_id} not found for ticker={ticker} strategy={strat_db}",
        )

    matching = [r for r in results if r.get("code_fingerprint") == current_fp]
    if not matching:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_comparable_backtest",
                "message": (
                    f"None of the {len(results)} saved backtest(s) for ticker={ticker} "
                    f"strategy={strat_db} were produced by the current engine code "
                    f"(fingerprint {current_fp}). Comparing live results against a run from "
                    "different code attributes the gap to the strategy when it belongs to a "
                    "code change. Re-run POST /backtest, or pass an explicit backtest_id to "
                    "override."
                ),
                "current_code_fingerprint": current_fp,
                "rejected_candidates": [_describe_backtest(r) for r in results[:10]],
            },
        )

    chosen = matching[0]  # get_backtest_results orders by id DESC
    return chosen, {
        "backtest_id_used": chosen.get("id"),
        "selected_by": "newest_matching_code_fingerprint",
        "current_code_fingerprint": current_fp,
        "backtest_code_fingerprint": chosen.get("code_fingerprint"),
        "code_fingerprint_match": True,
        "candidates_matching_code": len(matching),
        "candidates_rejected_stale_code": [
            _describe_backtest(r) for r in results if r.get("code_fingerprint") != current_fp
        ][:10],
    }


@app.get("/divergence-analysis")
def get_divergence_analysis(
    ticker: str,
    strategy: str = "Momentum",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    backtest_id: Optional[int] = None,
    forward_fill_live: bool = False,
    short_window: int = 50,
    long_window: int = 200,
    lookback_period: int = 120,
    stat_lookback: int = 60,
    entry_threshold: float = 2.0,
    exit_threshold: float = 0.5,
    include_robustness: bool = True,
    n_bootstrap: int = 1000,
):
    """
    Compare saved backtest to live snapshots; attribution, rolling gaps, and optional robustness (walk-forward, bootstrap CIs, etc.).
    """
    from analytics.divergence import build_full_report

    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    strat_db = _normalize_strategy_for_db(strategy)
    results = db.get_backtest_results(ticker=ticker, strategy=storage_aliases(strat_db))
    if not results:
        raise HTTPException(
            status_code=422,
            detail=f"No backtest results for ticker={ticker} strategy={strat_db}. Run POST /backtest first.",
        )
    row, selection = _select_backtest(results, backtest_id, ticker, strat_db)

    history = db.get_portfolio_history(strategy=None)
    report = build_full_report(
        row,
        history,
        start_date=start_date,
        end_date=end_date,
        forward_fill_live=forward_fill_live,
        short_window=short_window,
        long_window=long_window,
        lookback_period=lookback_period,
        stat_lookback=stat_lookback,
        entry_threshold=entry_threshold,
        exit_threshold=exit_threshold,
        include_robustness=include_robustness,
        n_bootstrap=n_bootstrap,
    )
    report["ticker"] = ticker
    report["strategy_query"] = strategy
    report["strategy_normalized"] = strat_db
    report["backtest_id"] = row.get("id")
    report["backtest_selection"] = selection
    return report


class BacktestRequest(BaseModel):
    ticker: str
    ticker_b: str = None
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"
    strategy: str = "Momentum"
    short_window: int = 50
    long_window: int = 200
    lookback_period: int = 120
    lookback: int = 60
    entry_threshold: float = 2.0
    exit_threshold: float = 0.5


def _build_strategy(strategy_name: str, short_window: int, long_window: int, lookback_period: int,
                    ticker_a: str = None, ticker_b: str = None, lookback: int = 60,
                    entry_threshold: float = 2.0, exit_threshold: float = 0.5):
    from strategies.momentum import MomentumStrategy
    from strategies.ma_crossover import MACrossoverStrategy
    from strategies.stat_arb import StatArbStrategy
    from strategies.naming import MA_CROSSOVER, STAT_ARB
    name = strategy_canonical(strategy_name)
    if name == STAT_ARB and ticker_a and ticker_b:
        return StatArbStrategy(ticker_a=ticker_a, ticker_b=ticker_b, lookback=lookback,
                               entry_threshold=entry_threshold, exit_threshold=exit_threshold)
    if name == MA_CROSSOVER:
        return MACrossoverStrategy(short_window=short_window, long_window=long_window)
    return MomentumStrategy(lookback_period=lookback_period)


@app.post("/backtest")
def run_backtest(req: BacktestRequest):
    """Run backtest for a ticker (or pair for Stat Arb) and save results. Returns the saved run."""
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    start_date = req.start_date
    end_date = req.end_date
    # Canonical from here down: this is what gets written to backtest_results.
    strategy_name = strategy_canonical(req.strategy)
    is_stat_arb = strategy_name == "Stat Arb"
    if is_stat_arb:
        ticker_b = (req.ticker_b or "").strip().upper()
        if not ticker_b:
            raise HTTPException(status_code=400, detail="Stat Arb requires ticker_b")
        if not is_valid_pair(ticker, ticker_b):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pair: {ticker}-{ticker_b}. Use preset pairs from the dropdown.",
            )
        pair_ticker = f"{ticker}-{ticker_b}"
    response_enrichment = {}
    old_cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        from data.loader import load_data
        from engine.backtest_engine import BacktestEngine
        from analytics.metrics import calculate_metrics
        if is_stat_arb:
            data_a = load_data(ticker, start_date, end_date)
            data_b = load_data(ticker_b, start_date, end_date)
            if data_a is None or len(data_a) == 0:
                raise HTTPException(status_code=422, detail=f"No data for {ticker} in range {start_date} to {end_date}")
            if data_b is None or len(data_b) == 0:
                raise HTTPException(status_code=422, detail=f"No data for {ticker_b} in range {start_date} to {end_date}")
            strategy = _build_strategy(
                strategy_name, req.short_window, req.long_window, req.lookback_period,
                ticker_a=ticker, ticker_b=ticker_b, lookback=req.lookback,
                entry_threshold=req.entry_threshold, exit_threshold=req.exit_threshold,
            )
            engine = BacktestEngine()
            results = engine.run_pair(data_a, data_b, strategy)
            metrics = calculate_metrics(results)
            benchmark = _compute_spy_benchmark(start_date, end_date, engine.initial_capital)
            pair_params = {
                "strategy": strategy_name,
                "ticker_a": ticker,
                "ticker_b": ticker_b,
                "lookback": int(req.lookback) if req.lookback is not None else 60,
                "entry_threshold": float(req.entry_threshold) if req.entry_threshold is not None else 2.0,
                "exit_threshold": float(req.exit_threshold) if req.exit_threshold is not None else 0.5,
            }
            saved_id = db.save_backtest_results(
                strategy_name, pair_ticker, start_date, end_date,
                float(metrics["total_return"]), float(metrics["sharpe_ratio"]),
                float(metrics["max_drawdown"]), int(metrics["num_trades"]),
                results["portfolio_values"],
                params=pair_params,
                code_fingerprint=backtest_fingerprint(),
            )
            # Return the run we just computed (do not re-fetch from DB) so client always gets fresh result
            pv = results["portfolio_values"]
            equity_list = [
                {"timestamp": str(pv.index[i])[:10], "portfolio_value": float(pv.iloc[i])}
                for i in range(len(pv))
            ]
            result = {
                "id": saved_id,
                "code_fingerprint": backtest_fingerprint(),
                "ticker": pair_ticker,
                "strategy": strategy_name,
                "start_date": start_date,
                "end_date": end_date,
                "total_return": float(metrics["total_return"]),
                "sharpe_ratio": float(metrics["sharpe_ratio"]),
                "max_drawdown": float(metrics["max_drawdown"]),
                "num_trades": int(metrics["num_trades"]),
                "avg_return_per_trade": metrics["avg_return_per_trade"],
                "daily_returns": metrics["daily_returns"],
                "equity_curve": _downsample_equity_curve(equity_list),
                "params_used": {
                    "strategy": strategy_name,
                    "ticker_a": ticker,
                    "ticker_b": ticker_b,
                    "lookback": int(req.lookback) if req.lookback is not None else 60,
                    "entry_threshold": float(req.entry_threshold) if req.entry_threshold is not None else 2.0,
                    "exit_threshold": float(req.exit_threshold) if req.exit_threshold is not None else 0.5,
                },
            }
            if benchmark:
                result["benchmark"] = benchmark
            return result
        data = load_data(ticker, start_date, end_date)
        if data is None or len(data) == 0:
            raise HTTPException(status_code=422, detail=f"No data for {ticker} in range {start_date} to {end_date}")
        strategy = _build_strategy(strategy_name, req.short_window, req.long_window, req.lookback_period)
        engine = BacktestEngine()
        results = engine.run(data, strategy)
        metrics = calculate_metrics(results)
        response_enrichment["daily_returns"] = metrics["daily_returns"]
        response_enrichment["avg_return_per_trade"] = metrics["avg_return_per_trade"]
        b = _compute_spy_benchmark(start_date, end_date, engine.initial_capital)
        if b:
            response_enrichment["benchmark"] = b
        saved_id = db.save_backtest_results(
            strategy_name, ticker, start_date, end_date,
            float(metrics["total_return"]), float(metrics["sharpe_ratio"]),
            float(metrics["max_drawdown"]), int(metrics["num_trades"]),
            results["portfolio_values"],
            params={
                "strategy": strategy_name,
                "short_window": req.short_window,
                "long_window": req.long_window,
                "lookback_period": req.lookback_period,
            },
            code_fingerprint=backtest_fingerprint(),
        )
        response_enrichment["id"] = saved_id
        response_enrichment["code_fingerprint"] = backtest_fingerprint()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.chdir(old_cwd)
    saved = db.get_backtest_results(ticker=ticker, strategy=storage_aliases(strategy_name))
    result = dict(saved[0]) if saved else {}
    result["equity_curve"] = _downsample_equity_curve(result.get("equity_curve") or [])
    result["params_used"] = {
        "strategy": strategy_name,
        "short_window": req.short_window,
        "long_window": req.long_window,
        "lookback_period": req.lookback_period,
    }
    result.update(response_enrichment)
    return result


@app.get("/live-benchmark")
def get_live_benchmark(strategy: str = None, time_range: str = "1Y"):
    """
    Live portfolio history vs SPY (buy & hold) over the same calendar window as `time_range`.
    Live equity is rebased so the first point in-window equals INITIAL_CAPITAL (same as SPY start).
    """
    start_date, end_inclusive = _time_range_to_dates(time_range)
    history = db.get_portfolio_history(strategy=strategy)
    points = []
    for snap in history:
        ts_raw = snap[1]
        pv = float(snap[3])
        d = (ts_raw or "")[:10]
        if d and start_date <= d <= end_inclusive:
            positions_raw = snap[5] if len(snap) > 5 else None
            try:
                positions = json.loads(positions_raw) if positions_raw else {}
            except (TypeError, json.JSONDecodeError):
                positions = {}
            points.append({
                "timestamp": d,
                "portfolio_value": pv,
                "cash": float(snap[4]) if snap[4] is not None else 0.0,
                "positions": positions,
            })
    points.sort(key=lambda x: x["timestamp"])

    # Drop readings that do not describe a state the account can be in before
    # any metric is computed off them. On 2026-07-07 Alpaca returned
    # portfolio_value == cash with no positions, sampled mid-mark at the close
    # between two days holding ~$105k; that single row put a 61% max drawdown
    # on a curve whose actual return is +1.65%. Excluded, not deleted - the row
    # stays in the table as evidence about the feed, and the response reports
    # how many were dropped so the number is never silently massaged.
    points, excluded_points = clean_series(points)
    trades = db.get_all_trades(strategy=strategy)
    num_trades = len(trades)

    if len(points) < 1:
        try:
            spy_payload = _spy_payload_for_live_window(start_date, end_inclusive)
        except Exception as e:
            logger.exception("live-benchmark (no portfolio history) failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
        return {
            "start_date": start_date,
            "end_date": end_inclusive,
            "time_range": time_range,
            "live_equity_curve": [],
            "spy_equity_curve": spy_payload["equity_curve"] if spy_payload else [],
            "live": {
                "total_return": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "daily_returns": [],
                "num_trades": num_trades,
                "avg_return_per_trade": None,
                "no_history": True,
            },
            "spy": spy_payload,
            "data_quality": {
                "snapshots_used": 0,
                "snapshots_excluded": len(excluded_points),
                "excluded": excluded_points[:20],
            },
        }

    try:
        from analytics.benchmark import metrics_from_sparse_equity_points

        ts_list = [p["timestamp"] for p in points]
        val_list = [p["portfolio_value"] for p in points]
        scale = INITIAL_CAPITAL / val_list[0] if val_list[0] else 1.0
        scaled_vals = [v * scale for v in val_list]
        live_curve_full = [
            {"timestamp": ts_list[i], "portfolio_value": scaled_vals[i]} for i in range(len(points))
        ]
        live_curve = _downsample_equity_curve(live_curve_full)

        # SPY spans exactly the live data, not the requested calendar window.
        # time_range only selects WHICH snapshots to include; the benchmark must
        # cover the same days those snapshots cover. Previously SPY used the raw
        # window, so time_range=ALL (12 years) benchmarked 115 days of live
        # trading against 12 years of SPY.
        spy_start, spy_end = ts_list[0], ts_list[-1]
        spy_payload = _spy_payload_for_live_window(spy_start, spy_end)

        lm = metrics_from_sparse_equity_points(ts_list, scaled_vals, INITIAL_CAPITAL)
        return {
            "start_date": spy_start,
            "end_date": spy_end,
            "time_range": time_range,
            "requested_window": {"start": start_date, "end": end_inclusive},
            "aligned_to_live_data": True,
            "live_equity_curve": live_curve,
            "spy_equity_curve": spy_payload["equity_curve"] if spy_payload else [],
            "live": {
                "total_return": lm["total_return"],
                "sharpe_ratio": lm["sharpe_ratio"],
                "max_drawdown": lm["max_drawdown"],
                "daily_returns": lm["daily_returns"],
                "num_trades": num_trades,
                "avg_return_per_trade": None,
            },
            "spy": spy_payload,
            "data_quality": {
                "snapshots_used": len(points),
                "snapshots_excluded": len(excluded_points),
                "excluded": excluded_points[:20],
            },
        }
    except Exception as e:
        logger.exception("live-benchmark failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/backtest-results")
def get_backtest_results(ticker: str = None, strategy: str = None):
    """Get saved backtest results, optionally filtered by ticker and/or strategy. Equity curves are downsampled."""
    results = db.get_backtest_results(
        ticker=ticker, strategy=storage_aliases(strategy) if strategy else None
    )
    for r in results:
        r["equity_curve"] = _downsample_equity_curve(r.get("equity_curve") or [])
    return {"results": results}


@app.get("/monte-carlo")
def get_monte_carlo(ticker: str, strategy: str = "Momentum", runs: int = 10000):
    """
    Run Monte Carlo simulation on backtest results.
    Uses saved backtest equity curve; run a backtest first for the given ticker and strategy.
    """
    from analytics.monte_carlo import run_monte_carlo

    results = db.get_backtest_results(
        ticker=ticker.strip().upper(), strategy=storage_aliases(strategy)
    )

    if not results:
        return {"error": "No backtest results found. Run backtest first."}

    equity_curve = results[0].get("equity_curve") or []
    if len(equity_curve) < 2:
        raise HTTPException(
            status_code=422,
            detail="Equity curve has too few points for Monte Carlo (need at least 2).",
        )

    portfolio_values = pd.Series([x["portfolio_value"] for x in equity_curve])
    initial_capital = float(equity_curve[0]["portfolio_value"]) if equity_curve else 100000.0

    mc_results = run_monte_carlo(
        portfolio_values, num_simulations=runs, initial_capital=initial_capital
    )

    if "error" in mc_results:
        raise HTTPException(status_code=422, detail=mc_results["error"])

    return mc_results


class RunExecutorRequest(BaseModel):
    strategy: str = "Momentum"
    ticker: str = "AAPL"
    ticker_b: str = None
    pair_name: str = None
    short_window: int = 50
    long_window: int = 200
    lookback_period: int = 120
    lookback: int = 60
    entry_threshold: float = 2.0
    exit_threshold: float = 0.5


@app.post("/run-executor")
def run_executor(req: RunExecutorRequest = None, _auth: bool = Depends(require_write_auth)):
    """Run the strategy executor once (paper trade). Requires X-API-Key; submits real orders."""
    req = req or RunExecutorRequest()
    ticker = (req.ticker or "AAPL").strip().upper()
    strategy_name = strategy_canonical(req.strategy)
    ticker_a = ticker
    ticker_b = None
    if strategy_name == "Stat Arb":
        if req.pair_name and "-" in req.pair_name:
            parts = req.pair_name.strip().upper().split("-")
            ticker_a, ticker_b = parts[0], parts[1]
        elif req.ticker_b:
            ticker_b = req.ticker_b.strip().upper()
        if not ticker_b:
            raise HTTPException(status_code=400, detail="Stat Arb requires ticker_b or pair_name (e.g. AAPL-MSFT)")
        if not is_valid_pair(ticker_a, ticker_b):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pair: {ticker_a}-{ticker_b}. Use preset pairs from the dropdown.",
            )
    old_cwd = os.getcwd()
    try:
        os.chdir(LIVE_DIR)
        from executor import StrategyExecutor
        strategy = _build_strategy(
            strategy_name, req.short_window, req.long_window, req.lookback_period,
            ticker_a=ticker_a, ticker_b=ticker_b, lookback=req.lookback,
            entry_threshold=req.entry_threshold, exit_threshold=req.exit_threshold,
        )
        params = {"short_window": req.short_window, "long_window": req.long_window, "lookback_period": req.lookback_period}
        if strategy_name == "Stat Arb":
            params = {"lookback": req.lookback, "entry_threshold": req.entry_threshold, "exit_threshold": req.exit_threshold}
        executor = StrategyExecutor(strategy, ticker=ticker_a, params=params)
        executor.run()
        # run() no longer snapshots; a single manual run is its own "run", so it
        # takes exactly one snapshot here (see StrategyExecutor.log_portfolio_snapshot).
        executor.log_portfolio_snapshot()
        out = {
            "ok": True,
            "message": "Strategy run complete. Check portfolio and trades.",
            "params_used": {
                "strategy": strategy_name,
                "short_window": req.short_window,
                "long_window": req.long_window,
                "lookback_period": req.lookback_period,
            },
        }
        if strategy_name == "Stat Arb":
            out["params_used"] = {"strategy": strategy_name, "ticker_a": ticker_a, "ticker_b": ticker_b,
                                  "lookback": req.lookback, "entry_threshold": req.entry_threshold, "exit_threshold": req.exit_threshold}
        return out
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.chdir(old_cwd)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)