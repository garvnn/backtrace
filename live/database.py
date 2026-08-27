"""
Database for storing trades and portfolio history.
"""

import sqlite3
from datetime import datetime, timezone
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
        # Additive migrations. Each ALTER is attempted and ignored if the column
        # already exists, so an existing production database keeps its rows.
        # Never reset trading.db to add a column: those rows are the record.
        for column_ddl in (
            'params TEXT',
            # Order lifecycle. price is the decision-time close (a DAY market
            # order placed after the close fills at the next open), so it is NOT
            # a fill price. filled_avg_price is, once reconciled.
            'filled_qty REAL',
            'filled_avg_price REAL',
            'reconciled_at TEXT',
            # Broker-side idempotency: Alpaca rejects a duplicate
            # client_order_id, so a double-fired run cannot double-submit.
            'client_order_id TEXT',
            # "queued_next_open" when the market was closed at submit time, so
            # the order queues to the next open and matches the backtest's
            # Open[T+1] fill model. "immediate_intraday" when the market was
            # open, meaning the signal came off a partial daily bar and filled
            # same-session - a trade the backtest cannot reproduce. Without this
            # tag, manual intraday runs silently contaminate the comparison.
            'fill_model TEXT',
        ):
            try:
                cursor.execute(f'ALTER TABLE trades ADD COLUMN {column_ddl}')
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
        # Additive migrations for backtest_results. Without params and
        # code_fingerprint, two rows with the same (strategy, ticker, date range)
        # are indistinguishable even when they disagree - which is exactly what
        # happened: 27 saved runs, three different answers, no way to tell which
        # code or which lookback produced any of them.
        for column_ddl in ('params TEXT', 'code_fingerprint TEXT', 'created_at TEXT'):
            try:
                cursor.execute(f'ALTER TABLE backtest_results ADD COLUMN {column_ddl}')
            except sqlite3.OperationalError:
                pass  # column already exists

        # Additive migration for portfolio_snapshots. data_quality records
        # whether a snapshot reconciled at write time; see live/snapshot_health.py.
        # Existing rows are left NULL, meaning "written before this check
        # existed" rather than "verified good" - the read side treats NULL as
        # unknown and classifies those rows by shape instead.
        try:
            cursor.execute('ALTER TABLE portfolio_snapshots ADD COLUMN data_quality TEXT')
        except sqlite3.OperationalError:
            pass  # column already exists

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
    
    # An order is settled once Alpaca reports one of these. Anything else is
    # still open and gets re-polled on the next reconciliation pass.
    TERMINAL_ORDER_STATUSES = ("filled", "canceled", "cancelled", "expired", "rejected")

    def log_trade(self, strategy, ticker, side, qty, price=None, order_id=None, status='submitted',
                  params=None, client_order_id=None, fill_model=None):
        """
        Record an order at submission time.

        price is the decision-time reference (prior close), not a fill price.
        Fills arrive later via update_trade_fill; until then filled_avg_price is
        NULL and status is whatever the broker returned on submit.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        params_json = json.dumps(params) if params is not None else None
        cursor.execute('''
            INSERT INTO trades
                (timestamp, strategy, ticker, side, qty, price, order_id, status, params,
                 client_order_id, fill_model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, ticker, side, qty, price, order_id, status,
              params_json, client_order_id, fill_model))

        conn.commit()
        conn.close()

    def get_unreconciled_orders(self, max_age_days=10):
        """
        Orders not yet in a terminal state, newest first.

        A DAY market order submitted after the close does not fill for ~17 hours,
        so polling synchronously at submit time cannot work. Instead the next
        scheduler run settles the previous run's orders. max_age_days bounds how
        far back to look so a permanently stuck row is not re-polled forever.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in self.TERMINAL_ORDER_STATUSES)
        cursor.execute(f'''
            SELECT id, timestamp, strategy, ticker, side, qty, price, order_id, status
            FROM trades
            WHERE order_id IS NOT NULL
              AND TRIM(order_id) != ''
              AND (status IS NULL OR LOWER(status) NOT IN ({placeholders}))
              AND julianday('now') - julianday(timestamp) <= ?
            ORDER BY timestamp DESC
        ''', (*self.TERMINAL_ORDER_STATUSES, max_age_days))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "timestamp": r[1], "strategy": r[2], "ticker": r[3],
                "side": r[4], "qty": r[5], "price": r[6], "order_id": r[7], "status": r[8],
            }
            for r in rows
        ]

    def update_trade_fill(self, trade_id, status, filled_qty=None, filled_avg_price=None):
        """Write back what the broker reports for an order. Returns True if a row changed."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE trades
            SET status = ?, filled_qty = ?, filled_avg_price = ?, reconciled_at = ?
            WHERE id = ?
        ''', (status, filled_qty, filled_avg_price, datetime.now().isoformat(), trade_id))
        changed = cursor.rowcount
        conn.commit()
        conn.close()
        return changed > 0
    
    def log_portfolio_snapshot(self, strategy, portfolio_value, cash, positions,
                               data_quality=None):
        """
        Log current portfolio state.

        data_quality is the verdict from snapshot_health.reconcile_snapshot at
        write time. Callers should not persist a snapshot that failed to
        reconcile at all; this records which of the passing outcomes it was, so
        a flat account and a mid-mark reading that merely looks flat can be
        told apart later.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO portfolio_snapshots
                (timestamp, strategy, portfolio_value, cash, positions, data_quality)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), strategy, portfolio_value, cash,
              json.dumps(positions), data_quality))

        conn.commit()
        conn.close()
    
    def save_backtest_results(self, strategy, ticker, start_date, end_date,
                             total_return, sharpe_ratio, max_drawdown, num_trades, equity_curve,
                             params=None, code_fingerprint=None):
        """
        Save a backtest run. Returns the new row id.

        params and code_fingerprint are what make a saved run reproducible.
        Without them, (strategy, ticker, start_date, end_date) is not a unique
        key for a result - it is a query that can return several disagreeing
        answers, and the caller has no way to tell which is which.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Convert equity curve to JSON
        equity_curve_json = equity_curve.to_json()
        params_json = json.dumps(params) if params is not None else None

        cursor.execute('''
            INSERT INTO backtest_results
            (strategy, ticker, start_date, end_date, total_return, sharpe_ratio,
             max_drawdown, num_trades, equity_curve, params, code_fingerprint, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (strategy, ticker, start_date, end_date, total_return, sharpe_ratio,
              max_drawdown, num_trades, equity_curve_json, params_json, code_fingerprint,
              # UTC-aware. The rest of this table's timestamps are naive host-local
              # time, which reads as one thing on a laptop in ET and another on
              # Railway's UTC containers; new columns do not inherit that.
              datetime.now(timezone.utc).isoformat()))

        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id

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
        cols = ('id, timestamp, strategy, ticker, side, qty, price, order_id, status, params, '
                'filled_qty, filled_avg_price, reconciled_at, client_order_id, fill_model')
        if strategy:
            cursor.execute(f'SELECT {cols} FROM trades WHERE strategy = ? ORDER BY timestamp DESC', (strategy,))
        else:
            cursor.execute(f'SELECT {cols} FROM trades ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        out = []
        for row in rows:
            params = None
            if row[9]:
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
                # Decision-time reference price, not the fill.
                "price": row[6],
                "order_id": row[7],
                "status": row[8],
                "params": params,
                "filled_qty": row[10],
                # The actual fill, once reconciled. Slippage is
                # filled_avg_price - price.
                "filled_avg_price": row[11],
                "reconciled_at": row[12],
                "client_order_id": row[13],
                "fill_model": row[14],
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
        """
        Get saved backtest results, optionally filtered by ticker and/or strategy.

        strategy accepts a string or a sequence of spellings. Rows written
        before the MA Crossover rename are stored as "MeanReversion", so a
        single-string exact match would hide them - callers pass
        strategies.naming.storage_aliases() to see both.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = ('SELECT id, strategy, ticker, start_date, end_date, total_return, sharpe_ratio, '
                 'max_drawdown, num_trades, equity_curve, params, code_fingerprint, created_at '
                 'FROM backtest_results')
        params = []
        clauses = []
        if ticker:
            clauses.append('ticker = ?')
            params.append(ticker)
        if strategy:
            names = [strategy] if isinstance(strategy, str) else list(strategy)
            if len(names) == 1:
                clauses.append('strategy = ?')
                params.append(names[0])
            else:
                clauses.append('strategy IN (%s)' % ','.join('?' * len(names)))
                params.extend(names)
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
                            # utcfromtimestamp is deprecated from Python 3.12;
                            # this runs on 3.14 in production.
                            ts_str = datetime.fromtimestamp(
                                ts_val / 1000.0, tz=timezone.utc
                            ).strftime("%Y-%m-%d")
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
                # Rows saved before these columns existed carry None. Those runs
                # are not reproducible and should not be compared against.
                "params": json.loads(row[10]) if row[10] else None,
                "code_fingerprint": row[11],
                "created_at": row[12],
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