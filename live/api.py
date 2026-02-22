"""
FastAPI backend for live trading dashboard.
"""

import sys
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

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

db = Database()


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
    """Get all trades, optionally filtered by strategy."""
    trades = db.get_all_trades(strategy=strategy)
    
    trades_list = []
    for trade in trades:
        trades_list.append({
            "id": trade[0],
            "timestamp": trade[1],
            "strategy": trade[2],
            "ticker": trade[3],
            "side": trade[4],
            "qty": trade[5],
            "price": trade[6],
            "order_id": trade[7],
            "status": trade[8]
        })
    
    return {"trades": trades_list}


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
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"
    strategy: str = "Momentum"


@app.post("/backtest")
def run_backtest(req: BacktestRequest):
    """Run backtest for a ticker and save results. Returns the saved run."""
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    start_date = req.start_date
    end_date = req.end_date
    strategy_name = req.strategy or "Momentum"
    old_cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        from data.loader import load_data
        from engine.backtest_engine import BacktestEngine
        from strategies.momentum import MomentumStrategy
        from strategies.mean_reversion import MeanReversionStrategy
        from analytics.metrics import calculate_metrics
        data = load_data(ticker, start_date, end_date)
        if data is None or len(data) == 0:
            raise HTTPException(status_code=422, detail=f"No data for {ticker} in range {start_date} to {end_date}")
        strategy_map = {"Momentum": MomentumStrategy(), "MeanReversion": MeanReversionStrategy()}
        strategy = strategy_map.get(strategy_name) or strategy_map["Momentum"]
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
    return saved[0] if saved else {}


@app.get("/backtest-results")
def get_backtest_results(ticker: str = None, strategy: str = None):
    """Get saved backtest results, optionally filtered by ticker and/or strategy."""
    results = db.get_backtest_results(ticker=ticker, strategy=strategy)
    return {"results": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)