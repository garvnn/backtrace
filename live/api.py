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
from fastapi import FastAPI, HTTPException
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

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
def delete_trade(trade_id: int):
    """Delete a trade by id."""
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


# Starting capital for live paper trading; return % is always from this baseline
INITIAL_CAPITAL = 100_000


@app.get("/performance")
def get_performance(strategy: str = None):
    """Get performance metrics. Total return is always from original 100k capital."""
    history = db.get_portfolio_history(strategy=strategy)
    initial_value = INITIAL_CAPITAL
    current_value = history[-1][3] if history else initial_value
    total_return = (current_value - initial_value) / initial_value

    trades = db.get_all_trades(strategy=strategy)

    return {
        "total_return": total_return,
        "num_trades": len(trades),
        "current_value": current_value,
        "initial_value": initial_value,
    }


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
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.stat_arb import StatArbStrategy
    if strategy_name == "Stat Arb" and ticker_a and ticker_b:
        return StatArbStrategy(ticker_a=ticker_a, ticker_b=ticker_b, lookback=lookback,
                               entry_threshold=entry_threshold, exit_threshold=exit_threshold)
    if strategy_name == "MeanReversion" or strategy_name == "MA Crossover":
        return MeanReversionStrategy(short_window=short_window, long_window=long_window)
    return MomentumStrategy(lookback_period=lookback_period)


@app.post("/backtest")
def run_backtest(req: BacktestRequest):
    """Run backtest for a ticker (or pair for Stat Arb) and save results. Returns the saved run."""
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    start_date = req.start_date
    end_date = req.end_date
    strategy_name = req.strategy or "Momentum"
    if strategy_name == "MA Crossover":
        strategy_name = "MeanReversion"
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
            db.save_backtest_results(
                strategy_name, pair_ticker, start_date, end_date,
                float(metrics["total_return"]), float(metrics["sharpe_ratio"]),
                float(metrics["max_drawdown"]), int(metrics["num_trades"]),
                results["portfolio_values"],
            )
            # Return the run we just computed (do not re-fetch from DB) so client always gets fresh result
            pv = results["portfolio_values"]
            equity_list = [
                {"timestamp": str(pv.index[i])[:10], "portfolio_value": float(pv.iloc[i])}
                for i in range(len(pv))
            ]
            result = {
                "ticker": pair_ticker,
                "strategy": strategy_name,
                "start_date": start_date,
                "end_date": end_date,
                "total_return": float(metrics["total_return"]),
                "sharpe_ratio": float(metrics["sharpe_ratio"]),
                "max_drawdown": float(metrics["max_drawdown"]),
                "num_trades": int(metrics["num_trades"]),
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
            return result
        data = load_data(ticker, start_date, end_date)
        if data is None or len(data) == 0:
            raise HTTPException(status_code=422, detail=f"No data for {ticker} in range {start_date} to {end_date}")
        strategy = _build_strategy(strategy_name, req.short_window, req.long_window, req.lookback_period)
        engine = BacktestEngine()
        results = engine.run(data, strategy)
        metrics = calculate_metrics(results)
        db.save_backtest_results(
            strategy_name, ticker, start_date, end_date,
            float(metrics["total_return"]), float(metrics["sharpe_ratio"]),
            float(metrics["max_drawdown"]), int(metrics["num_trades"]),
            results["portfolio_values"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.chdir(old_cwd)
    saved = db.get_backtest_results(ticker=ticker, strategy=strategy_name)
    result = dict(saved[0]) if saved else {}
    result["equity_curve"] = _downsample_equity_curve(result.get("equity_curve") or [])
    result["params_used"] = {
        "strategy": strategy_name,
        "short_window": req.short_window,
        "long_window": req.long_window,
        "lookback_period": req.lookback_period,
    }
    return result


@app.get("/backtest-results")
def get_backtest_results(ticker: str = None, strategy: str = None):
    """Get saved backtest results, optionally filtered by ticker and/or strategy. Equity curves are downsampled."""
    results = db.get_backtest_results(ticker=ticker, strategy=strategy)
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

    normalized_strategy = "MeanReversion" if strategy == "MA Crossover" else strategy
    results = db.get_backtest_results(ticker=ticker.strip().upper(), strategy=normalized_strategy)

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
def run_executor(req: RunExecutorRequest = None):
    """Run the strategy executor once (paper trade) with selected strategy and params."""
    req = req or RunExecutorRequest()
    ticker = (req.ticker or "AAPL").strip().upper()
    strategy_name = req.strategy or "Momentum"
    if strategy_name == "MA Crossover":
        strategy_name = "MeanReversion"
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