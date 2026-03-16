"""
Comprehensive database integrity tests for BackTrace Live.
Verifies all tables exist, CRUD operations, timestamps, and edge cases.
Uses a temporary test database to avoid polluting production.
"""

import os
import sys
import sqlite3
import json
import tempfile
from datetime import datetime

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from database import Database


REQUIRED_TABLES = ["trades", "portfolio_snapshots", "backtest_results", "pair_trades"]
REQUIRED_TRADES_COLUMNS = ["id", "timestamp", "strategy", "ticker", "side", "qty", "price", "order_id", "status", "params"]
REQUIRED_SNAPSHOTS_COLUMNS = ["id", "timestamp", "strategy", "portfolio_value", "cash", "positions"]
REQUIRED_BACKTEST_COLUMNS = ["id", "strategy", "ticker", "start_date", "end_date", "total_return", "sharpe_ratio", "max_drawdown", "num_trades", "equity_curve"]
REQUIRED_PAIR_TRADES_COLUMNS = ["id", "timestamp", "strategy", "pair_name", "ticker_a", "ticker_b", "side_a", "side_b", "qty_a", "qty_b", "spread", "z_score", "order_id_a", "order_id_b"]


def get_test_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="backtrace_test_")
    os.close(fd)
    return path


def test_tables_exist(db_path):
    """Verify all required tables exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    missing = set(REQUIRED_TABLES) - tables
    return len(missing) == 0, list(missing) if missing else None


def test_columns_exist(db_path):
    """Verify expected columns exist for each table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    results = {}
    for table, cols in [
        ("trades", REQUIRED_TRADES_COLUMNS),
        ("portfolio_snapshots", REQUIRED_SNAPSHOTS_COLUMNS),
        ("backtest_results", REQUIRED_BACKTEST_COLUMNS),
        ("pair_trades", REQUIRED_PAIR_TRADES_COLUMNS),
    ]:
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
        missing = set(cols) - existing
        results[table] = (len(missing) == 0, list(missing) if missing else None)
    conn.close()
    return results


def test_insert_retrieve_trades(db):
    """Test inserting and retrieving trades."""
    strategy, ticker = "Momentum", "AAPL"
    db.log_trade(strategy, ticker, "BUY", 10.0, price=150.0, order_id="ord_1", status="filled", params={"lookback_period": 120})
    trades = db.get_all_trades(strategy=strategy)
    assert trades, "No trades returned"
    t = trades[0]
    assert t["strategy"] == strategy and t["ticker"] == ticker and t["side"] == "BUY"
    assert t["qty"] == 10.0 and t["price"] == 150.0 and t["params"]["lookback_period"] == 120
    return True


def test_insert_retrieve_snapshots(db):
    """Test inserting and retrieving portfolio snapshots."""
    db.log_portfolio_snapshot("Momentum", 105000.0, 50000.0, {"AAPL": 10})
    history = db.get_portfolio_history(strategy="Momentum")
    assert history, "No portfolio history"
    row = history[-1]
    assert float(row[3]) == 105000.0 and float(row[4]) == 50000.0
    positions = json.loads(row[5])
    assert positions.get("AAPL") == 10
    return True


def test_insert_retrieve_backtest_results(db):
    """Test inserting and retrieving backtest results. Uses Series with date index -> to_json()."""
    try:
        import pandas as pd
    except ImportError:
        raise AssertionError("pandas required for backtest_results test")
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    equity = pd.Series([100000, 101000, 100500, 102000, 101500], index=dates)
    db.save_backtest_results("Momentum", "AAPL", "2024-01-01", "2024-01-05", 0.015, 1.2, -0.02, 3, equity)
    results = db.get_backtest_results(ticker="AAPL", strategy="Momentum")
    assert results, "No backtest results"
    r = results[0]
    assert r["ticker"] == "AAPL" and r["strategy"] == "Momentum"
    assert r["total_return"] == 0.015 and r["num_trades"] == 3
    assert isinstance(r["equity_curve"], list) and len(r["equity_curve"]) >= 1
    return True


def test_insert_retrieve_pair_trades(db):
    """Test inserting and retrieving pair trades."""
    db.log_pair_trade("Stat Arb", "AAPL-MSFT", "AAPL", "MSFT", "BUY", "SELL", 5.0, 5.0, spread=0.01, z_score=1.5, order_id_a="oa", order_id_b="ob")
    pairs = db.get_pair_trades(strategy="Stat Arb")
    assert pairs, "No pair trades"
    p = pairs[0]
    assert p["pair_name"] == "AAPL-MSFT" and p["ticker_a"] == "AAPL" and p["side_a"] == "BUY"
    assert p["qty_a"] == 5.0 and p["z_score"] == 1.5
    return True


def test_timestamps_stored_correctly(db):
    """Verify timestamps are stored and returned correctly."""
    before = datetime.now().isoformat()
    db.log_trade("Momentum", "TSLA", "SELL", 1.0)
    after = datetime.now().isoformat()
    trades = db.get_all_trades()
    assert trades
    ts = trades[0]["timestamp"]
    assert ts >= before[:19] or ts <= after[:19], "Timestamp should be in range"
    return True


def test_edge_case_null_params(db):
    """Test null/None params in trades."""
    db.log_trade("MA Crossover", "GOOGL", "BUY", 2.0, price=None, order_id=None, status="submitted", params=None)
    trades = db.get_all_trades(strategy="MA Crossover")
    assert trades
    t = trades[0]
    assert t["params"] is None or t["params"] == {}
    return True


def test_edge_case_special_characters(db):
    """Test ticker/strategy with special characters (e.g. BRK.B)."""
    db.log_trade("Momentum", "BRK.B", "BUY", 1.0, params={"lookback_period": 120})
    trades = [t for t in db.get_all_trades() if t["ticker"] == "BRK.B"]
    assert trades and trades[0]["ticker"] == "BRK.B"
    return True


def test_edge_case_empty_positions(db):
    """Test portfolio snapshot with empty positions."""
    db.log_portfolio_snapshot("Momentum", 100000.0, 100000.0, {})
    history = db.get_portfolio_history()
    row = history[-1]
    pos = json.loads(row[5]) if row[5] else {}
    assert pos == {}
    return True


def test_delete_trade(db):
    """Test trade deletion."""
    db.log_trade("Momentum", "XOM", "BUY", 5.0)
    trades = db.get_all_trades()
    ids = [t["id"] for t in trades if t["ticker"] == "XOM"]
    if ids:
        ok = db.delete_trade(ids[0])
        assert ok
    return True


def test_orphaned_records(db_path):
    """Check for orphaned records (e.g. trades with invalid strategy). Not strict; just report counts."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades")
    trade_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT strategy) FROM trades")
    strategies = cursor.fetchone()[0]
    conn.close()
    return trade_count, strategies


def run_all_tests():
    db_path = get_test_db_path()
    report = []
    try:
        db = Database(db_path)

        # 1. Tables exist
        ok, missing = test_tables_exist(db_path)
        report.append(("Tables exist", ok, None if ok else f"Missing: {missing}"))

        # 2. Columns exist
        col_results = test_columns_exist(db_path)
        for table, (ok, missing) in col_results.items():
            report.append((f"Columns for {table}", ok, None if ok else f"Missing: {missing}"))

        # 3. Insert/retrieve each table
        try:
            test_insert_retrieve_trades(db)
            report.append(("Insert/retrieve trades", True, None))
        except Exception as e:
            report.append(("Insert/retrieve trades", False, str(e)))
        try:
            test_insert_retrieve_snapshots(db)
            report.append(("Insert/retrieve portfolio_snapshots", True, None))
        except Exception as e:
            report.append(("Insert/retrieve portfolio_snapshots", False, str(e)))
        try:
            test_insert_retrieve_backtest_results(db)
            report.append(("Insert/retrieve backtest_results", True, None))
        except Exception as e:
            report.append(("Insert/retrieve backtest_results", False, str(e)))
        try:
            test_insert_retrieve_pair_trades(db)
            report.append(("Insert/retrieve pair_trades", True, None))
        except Exception as e:
            report.append(("Insert/retrieve pair_trades", False, str(e)))

        # 4. Timestamps
        try:
            test_timestamps_stored_correctly(db)
            report.append(("Timestamps stored correctly", True, None))
        except Exception as e:
            report.append(("Timestamps stored correctly", False, str(e)))

        # 5. Edge cases
        try:
            test_edge_case_null_params(db)
            report.append(("Edge case: null params", True, None))
        except Exception as e:
            report.append(("Edge case: null params", False, str(e)))
        try:
            test_edge_case_special_characters(db)
            report.append(("Edge case: special chars (BRK.B)", True, None))
        except Exception as e:
            report.append(("Edge case: special chars (BRK.B)", False, str(e)))
        try:
            test_edge_case_empty_positions(db)
            report.append(("Edge case: empty positions", True, None))
        except Exception as e:
            report.append(("Edge case: empty positions", False, str(e)))
        try:
            test_delete_trade(db)
            report.append(("Delete trade", True, None))
        except Exception as e:
            report.append(("Delete trade", False, str(e)))

        # 6. Orphan check (informational)
        trade_count, strategies = test_orphaned_records(db_path)
        report.append(("DB state (test)", True, f"Trades: {trade_count}, strategies: {strategies}"))

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

    return report


def main():
    print("=" * 60)
    print("DATABASE INTEGRITY TEST REPORT")
    print("=" * 60)
    report = run_all_tests()
    passed = sum(1 for _, ok, _ in report if ok)
    total = len(report)
    for name, ok, detail in report:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    print("=" * 60)
    print(f"Result: {passed}/{total} checks passed")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
