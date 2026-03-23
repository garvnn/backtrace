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
                status TEXT,
                params TEXT
            )
        ''')
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN params TEXT')
        except sqlite3.OperationalError:
            pass  # column already exists
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
        
        # Pair trades table (stat arb)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pair_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                pair_name TEXT NOT NULL,
                ticker_a TEXT NOT NULL,
                ticker_b TEXT NOT NULL,
                side_a TEXT NOT NULL,
                side_b TEXT NOT NULL,
                qty_a REAL NOT NULL,
                qty_b REAL NOT NULL,
                spread REAL,
                z_score REAL,
                order_id_a TEXT,
                order_id_b TEXT
            )
        ''')

        # Execution decision logs (includes no-trade reasons)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal TEXT,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                details_json TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        print("Database initialized")
    
    def log_trade(self, strategy, ticker, side, qty, price=None, order_id=None, status='submitted', params=None):
        """Log a trade to database. params is optional dict stored as JSON (e.g. short_window, long_window, lookback_period)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        params_json = json.dumps(params) if params is not None else None
        cursor.execute('''
            INSERT INTO trades (timestamp, strategy, ticker, side, qty, price, order_id, status, params)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, ticker, side, qty, price, order_id, status, params_json))
        
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

    def get_last_executed_signal(self, strategy, ticker):
        """Return 1 if most recent trade for (strategy, ticker) was BUY, 0 if SELL, None if no trades."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT side FROM trades WHERE strategy = ? AND ticker = ? ORDER BY timestamp DESC LIMIT 1',
            (strategy, ticker)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        side = (row[0] or '').upper()
        if side == 'BUY':
            return 1
        if side == 'SELL':
            return 0
        return None
    
    def get_all_trades(self, strategy=None):
        """Get all trades, optionally filtered by strategy. Returns list of dicts with id, timestamp, strategy, ticker, side, qty, price, order_id, status, params (parsed)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if strategy:
            cursor.execute('SELECT id, timestamp, strategy, ticker, side, qty, price, order_id, status, params FROM trades WHERE strategy = ? ORDER BY timestamp DESC', (strategy,))
        else:
            cursor.execute('SELECT id, timestamp, strategy, ticker, side, qty, price, order_id, status, params FROM trades ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        out = []
        for row in rows:
            params = None
            if len(row) > 9 and row[9]:
                try:
                    params = json.loads(row[9])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append({
                "id": row[0],
                "timestamp": row[1],
                "strategy": row[2],
                "ticker": row[3],
                "side": row[4],
                "qty": row[5],
                "price": row[6],
                "order_id": row[7],
                "status": row[8],
                "params": params,
            })
        return out

    def delete_trade(self, trade_id):
        """Delete a trade by id. Returns True if a row was deleted."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM trades WHERE id = ?', (trade_id,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted > 0

    def log_pair_trade(self, strategy, pair_name, ticker_a, ticker_b, side_a, side_b,
                       qty_a, qty_b, spread=None, z_score=None, order_id_a=None, order_id_b=None):
        """Log a pair trade (both legs) for stat arb."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pair_trades 
            (timestamp, strategy, pair_name, ticker_a, ticker_b, side_a, side_b, qty_a, qty_b, spread, z_score, order_id_a, order_id_b)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, pair_name, ticker_a, ticker_b, side_a, side_b,
              qty_a, qty_b, spread, z_score, order_id_a, order_id_b))
        conn.commit()
        conn.close()

    def get_pair_trades(self, strategy=None):
        """Get pair trades, optionally filtered by strategy. Returns list of dicts."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if strategy:
            cursor.execute('''
                SELECT id, timestamp, strategy, pair_name, ticker_a, ticker_b, side_a, side_b,
                       qty_a, qty_b, spread, z_score, order_id_a, order_id_b
                FROM pair_trades WHERE strategy = ? ORDER BY timestamp DESC
            ''', (strategy,))
        else:
            cursor.execute('''
                SELECT id, timestamp, strategy, pair_name, ticker_a, ticker_b, side_a, side_b,
                       qty_a, qty_b, spread, z_score, order_id_a, order_id_b
                FROM pair_trades ORDER BY timestamp DESC
            ''')
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "strategy": row[2],
                "pair_name": row[3],
                "ticker_a": row[4],
                "ticker_b": row[5],
                "side_a": row[6],
                "side_b": row[7],
                "qty_a": row[8],
                "qty_b": row[9],
                "spread": row[10],
                "z_score": row[11],
                "order_id_a": row[12],
                "order_id_b": row[13],
            }
            for row in rows
        ]
    
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

    def log_execution(self, strategy, ticker, signal, action, reason, details=None):
        """Log execution decision. details is optional dict with full context."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        details_json = json.dumps(details) if details is not None else None
        cursor.execute('''
            INSERT INTO execution_logs (timestamp, strategy, ticker, signal, action, reason, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, ticker, signal, action, reason, details_json))
        conn.commit()
        conn.close()

    def get_execution_logs(self, strategy=None, ticker=None, limit=200):
        """Get execution decision logs newest-first with parsed details."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = '''
            SELECT id, timestamp, strategy, ticker, signal, action, reason, details_json
            FROM execution_logs
        '''
        params = []
        clauses = []
        if strategy:
            clauses.append('strategy = ?')
            params.append(strategy)
        if ticker:
            clauses.append('ticker = ?')
            params.append(ticker)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(int(limit))
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        out = []
        for row in rows:
            details = None
            if row[7]:
                try:
                    details = json.loads(row[7])
                except (json.JSONDecodeError, TypeError):
                    details = None
            out.append({
                "id": row[0],
                "timestamp": row[1],
                "strategy": row[2],
                "ticker": row[3],
                "signal": row[4],
                "action": row[5],
                "reason": row[6],
                "details": details,
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