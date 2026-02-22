"""
Database for storing trades and portfolio history.
"""

import sqlite3
from datetime import datetime
import json

class Database:
    def __init__(self, db_path='trading.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Create tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL,
                order_id TEXT,
                status TEXT
            )
        ''')
        
        # Portfolio snapshots table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                portfolio_value REAL NOT NULL,
                cash REAL NOT NULL,
                positions TEXT
            )
        ''')
        
        # Backtest results table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                ticker TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                total_return REAL,
                sharpe_ratio REAL,
                max_drawdown REAL,
                num_trades INTEGER,
                equity_curve TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        print("Database initialized")
    
    def log_trade(self, strategy, ticker, side, qty, price=None, order_id=None, status='submitted'):
        """Log a trade to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (timestamp, strategy, ticker, side, qty, price, order_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, ticker, side, qty, price, order_id, status))
        
        conn.commit()
        conn.close()
    
    def log_portfolio_snapshot(self, strategy, portfolio_value, cash, positions):
        """Log current portfolio state."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO portfolio_snapshots (timestamp, strategy, portfolio_value, cash, positions)
            VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, portfolio_value, cash, json.dumps(positions)))
        
        conn.commit()
        conn.close()
    
    def save_backtest_results(self, strategy, ticker, start_date, end_date, 
                             total_return, sharpe_ratio, max_drawdown, num_trades, equity_curve):
        """Save backtest results for comparison."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Convert equity curve to JSON
        equity_curve_json = equity_curve.to_json()
        
        cursor.execute('''
            INSERT INTO backtest_results 
            (strategy, ticker, start_date, end_date, total_return, sharpe_ratio, 
             max_drawdown, num_trades, equity_curve)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (strategy, ticker, start_date, end_date, total_return, sharpe_ratio,
              max_drawdown, num_trades, equity_curve_json))
        
        conn.commit()
        conn.close()
    
    def get_all_trades(self, strategy=None):
        """Get all trades, optionally filtered by strategy."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if strategy:
            cursor.execute('SELECT * FROM trades WHERE strategy = ? ORDER BY timestamp DESC', (strategy,))
        else:
            cursor.execute('SELECT * FROM trades ORDER BY timestamp DESC')
        
        trades = cursor.fetchall()
        conn.close()
        return trades
    
    def get_portfolio_history(self, strategy=None):
        """Get portfolio value history."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if strategy:
            cursor.execute('SELECT * FROM portfolio_snapshots WHERE strategy = ? ORDER BY timestamp', (strategy,))
        else:
            cursor.execute('SELECT * FROM portfolio_snapshots ORDER BY timestamp')
        
        history = cursor.fetchall()
        conn.close()
        return history

    def get_backtest_results(self, ticker=None, strategy=None):
        """Get saved backtest results, optionally filtered by ticker and/or strategy."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = 'SELECT id, strategy, ticker, start_date, end_date, total_return, sharpe_ratio, max_drawdown, num_trades, equity_curve FROM backtest_results'
        params = []
        clauses = []
        if ticker:
            clauses.append('ticker = ?')
            params.append(ticker)
        if strategy:
            clauses.append('strategy = ?')
            params.append(strategy)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY id DESC'
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        out = []
        for row in rows:
            ec_raw = row[9]
            equity_curve = []
            if ec_raw:
                try:
                    ec_dict = json.loads(ec_raw)
                    for ts, val in ec_dict.items():
                        try:
                            ts_val = int(ts)
                            ts_str = datetime.utcfromtimestamp(ts_val / 1000.0).strftime("%Y-%m-%d")
                        except (ValueError, TypeError):
                            ts_str = str(ts)
                        equity_curve.append({"timestamp": ts_str, "portfolio_value": float(val)})
                    equity_curve.sort(key=lambda x: x["timestamp"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append({
                "id": row[0],
                "strategy": row[1],
                "ticker": row[2],
                "start_date": row[3],
                "end_date": row[4],
                "total_return": row[5],
                "sharpe_ratio": row[6],
                "max_drawdown": row[7],
                "num_trades": row[8],
                "equity_curve": equity_curve,
            })
        return out


if __name__ == "__main__":
    # Test the database
    db = Database()
    
    # Test logging a trade
    db.log_trade('Momentum', 'AAPL', 'BUY', 10, 234.50, 'test123', 'filled')
    
    # Test logging portfolio snapshot
    db.log_portfolio_snapshot('Momentum', 100000.0, 50000.0, {'AAPL': 10})
    
    # Get trades
    trades = db.get_all_trades()
    print(f"\nTrades in database: {len(trades)}")
    print(trades[-1])