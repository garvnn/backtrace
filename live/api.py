"""
FastAPI backend for live trading dashboard.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)