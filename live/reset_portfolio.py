"""
One-time script to reset the paper portfolio and local DB to $100k starting capital.

- Closes all Alpaca positions (sells everything).
- Clears trades, portfolio_snapshots, and backtest_results tables.
- Inserts initial portfolio snapshot: $100,000 cash, 0 positions.

Run manually when needed: python live/reset_portfolio.py
(From project root. Or from live/: python reset_portfolio.py)
"""

import os
import sys

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != LIVE_DIR:
    os.chdir(LIVE_DIR)
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(LIVE_DIR, ".env"))

def main():
    # 1. Close all Alpaca positions
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        print("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in live/.env. Skipping Alpaca close.")
    else:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        client = TradingClient(api_key, secret_key, paper=True)
        positions = client.get_all_positions()
        closed = 0
        for pos in positions:
            symbol = pos.symbol
            qty = abs(float(pos.qty))
            if qty <= 0:
                continue
            side = OrderSide.SELL if float(pos.qty) > 0 else OrderSide.BUY
            try:
                client.submit_order(
                    MarketOrderRequest(symbol=symbol, qty=qty, side=side, time_in_force=TimeInForce.DAY)
                )
                print(f"  Closed {symbol}: {qty} shares ({side.value})")
                closed += 1
            except Exception as e:
                print(f"  Failed to close {symbol}: {e}")
        print(f"Alpaca: closed {closed} position(s).")

    # 2. Clear local DB tables (trades, portfolio_snapshots, backtest_results)
    import sqlite3
    db_path = os.path.join(LIVE_DIR, "trading.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM trades")
    trades_deleted = cur.rowcount
    cur.execute("DELETE FROM portfolio_snapshots")
    snapshots_deleted = cur.rowcount
    cur.execute("DELETE FROM backtest_results")
    backtest_deleted = cur.rowcount
    conn.commit()
    conn.close()

    # 3. Insert initial $100k snapshot via Database (single source for Dashboard + Portfolio)
    from database import Database
    db = Database(db_path)
    db.log_portfolio_snapshot(
        strategy='Initial',
        portfolio_value=100000.0,
        cash=100000.0,
        positions={},
    )

    print(f"Cleared {trades_deleted} trade(s), {snapshots_deleted} snapshot(s), {backtest_deleted} backtest(s).")
    print("Portfolio reset to $100,000 starting capital.")

if __name__ == "__main__":
    main()
