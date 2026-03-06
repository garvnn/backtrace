"""
FastAPI backend for live trading dashboard.
"""

import sys
import os
LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import Database
import json

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database(os.path.join(LIVE_DIR, "trading.db"))

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


@app.get("/portfolio")
def get_portfolio():
    """Get current portfolio state."""
    history = db.get_portfolio_history()
    
    if not history:
        return {"portfolio_value": 0, "cash": 0, "positions": {}}
    
    # Get latest snapshot
    latest = history[-1]
    
    return {
        "portfolio_value": latest[3],
        "cash": latest[4],
        "positions": json.loads(latest[5]),
        "timestamp": latest[1],
        "strategy": latest[2]
    }


@app.get("/trades")
def get_trades(strategy: str = None):
    """Get all trades, optionally filtered by strategy. Each trade includes params if stored."""
    trades = db.get_all_trades(strategy=strategy)
    return {"trades": trades}


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
        history_list.append({
            "timestamp": snapshot[1],
            "strategy": snapshot[2],
            "portfolio_value": snapshot[3],
            "cash": snapshot[4],
            "positions": json.loads(snapshot[5])
        })
    
    return {"history": history_list}


@app.get("/performance")
def get_performance(strategy: str = None):
    """Get performance metrics."""
    history = db.get_portfolio_history(strategy=strategy)
    
    if len(history) < 2:
        return {
            "total_return": 0,
            "num_trades": 0,
            "current_value": 100000
        }
    
    initial_value = history[0][3]
    current_value = history[-1][3]
    total_return = (current_value - initial_value) / initial_value
    
    trades = db.get_all_trades(strategy=strategy)
    
    return {
        "total_return": total_return,
        "num_trades": len(trades),
        "current_value": current_value,
        "initial_value": initial_value
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