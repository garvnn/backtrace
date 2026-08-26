"""
Portfolio invariant tests for BackTrace Live.

Run after an executor cycle against the same DB_PATH the executor writes to:
  export DB_PATH=/tmp/backtrace_invariant_test.db
  pytest live/test_invariants.py -v -s
"""

import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest
from dotenv import load_dotenv

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from database import Database
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.stat_arb import StatArbStrategy
from trading_constants import MAX_DOLLAR_PER_STOCK

load_dotenv(os.path.join(LIVE_DIR, ".env"))

TOLERANCE = 0.01
POSITION_CAP = MAX_DOLLAR_PER_STOCK
CAP_BUFFER = 1.05
VALID_SIGNALS = {-1, 0, 1}
FILL_STATUSES = {"filled", "partially_filled"}


def flag(msg):
    """Surface missing data as a visible failure rather than a silent skip."""
    pytest.fail(f"FLAGGED: {msg}")


def print_result(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def get_latest_snapshot(db):
    """Return the most recent portfolio_snapshots row, or None."""
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, timestamp, strategy, portfolio_value, cash, positions
        FROM portfolio_snapshots
        ORDER BY timestamp DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    conn.close()
    return row


def _get_alpaca_prices(symbols):
    """Fetch current_price per symbol from Alpaca positions. Returns dict or None if unavailable."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key or not symbols:
        return None
    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(api_key, secret_key, paper=True)
        prices = {}
        for pos in client.get_all_positions():
            if pos.symbol in symbols:
                if hasattr(pos, "current_price") and pos.current_price:
                    prices[pos.symbol] = float(pos.current_price)
                elif pos.market_value and pos.qty:
                    prices[pos.symbol] = float(pos.market_value) / abs(float(pos.qty))
        return prices
    except Exception:
        return None


def _get_trade_prices(db, tickers):
    """Latest trade price per ticker from trades table."""
    prices = {}
    for trade in db.get_all_trades():
        ticker = trade["ticker"]
        if ticker in tickers and ticker not in prices and trade.get("price") is not None:
            prices[ticker] = float(trade["price"])
    return prices


def _get_entry_prices(db, tickers):
    """Most recent BUY price per ticker from trades table."""
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    prices = {}
    for ticker in tickers:
        cursor.execute(
            """
            SELECT price FROM trades
            WHERE ticker = ? AND UPPER(side) = 'BUY' AND price IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = cursor.fetchone()
        if row:
            prices[ticker] = float(row[0])
    conn.close()
    return prices


def _make_synthetic_ohlcv(n_rows=250, seed=42):
    """Build synthetic OHLCV DataFrame for strategy signal tests."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=n_rows, freq="B")
    close = 100.0 + np.cumsum(rng.normal(0, 1, n_rows))
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.002, n_rows)),
            "High": close * (1 + np.abs(rng.normal(0, 0.005, n_rows))),
            "Low": close * (1 - np.abs(rng.normal(0, 0.005, n_rows))),
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, n_rows),
        },
        index=dates,
    )


def _assert_valid_signals(series, strategy_name):
    values = set(series.dropna().unique())
    invalid = values - VALID_SIGNALS
    assert not invalid, f"{strategy_name} produced invalid signals: {invalid}"


@pytest.mark.invariant
def test_cash_never_negative(db):
    """
    WHAT: Latest portfolio snapshot cash balance must be >= 0.
    WHY: Negative cash indicates over-leveraging or an accounting error that
         could cause rejected orders or unintended margin usage.
    """
    snapshot = get_latest_snapshot(db)
    if snapshot is None:
        flag("no portfolio snapshots in DB")

    cash = float(snapshot[4])
    passed = cash >= 0
    print_result("test_cash_never_negative", passed, f"cash={cash:,.2f}")
    assert passed, f"Cash is negative: {cash}"


@pytest.mark.invariant
def test_portfolio_value_equals_cash_plus_positions(db):
    """
    WHAT: portfolio_value must equal cash + sum(qty * current_price) within tolerance.
    WHY: A mismatch means the snapshot is stale or inconsistent with actual holdings.
    """
    snapshot = get_latest_snapshot(db)
    if snapshot is None:
        flag("no portfolio snapshots in DB")

    portfolio_value = float(snapshot[3])
    cash = float(snapshot[4])
    positions_raw = snapshot[5]
    positions = json.loads(positions_raw) if positions_raw else {}

    if not positions:
        expected = cash
        passed = abs(portfolio_value - expected) <= TOLERANCE
        print_result(
            "test_portfolio_value_equals_cash_plus_positions",
            passed,
            f"portfolio_value={portfolio_value:,.2f}, expected={expected:,.2f} (no positions)",
        )
        assert passed, f"portfolio_value {portfolio_value} != cash {cash}"
        return

    tickers = [t for t, q in positions.items() if q]
    prices = _get_alpaca_prices(tickers) or {}
    missing = [t for t in tickers if t not in prices]
    if missing:
        trade_prices = _get_trade_prices(db, missing)
        prices.update(trade_prices)
        missing = [t for t in tickers if t not in prices]

    if missing:
        flag(f"missing current_price for: {', '.join(missing)}")

    position_value = sum(float(qty) * prices[ticker] for ticker, qty in positions.items() if qty)
    expected = cash + position_value
    passed = abs(portfolio_value - expected) <= TOLERANCE
    print_result(
        "test_portfolio_value_equals_cash_plus_positions",
        passed,
        f"portfolio_value={portfolio_value:,.2f}, expected={expected:,.2f}",
    )
    assert passed, f"portfolio_value {portfolio_value} != cash+positions {expected}"


@pytest.mark.invariant
def test_no_duplicate_orders_same_day(db):
    """
    WHAT: At most one order per (ticker, strategy, date) in the trades table.
    WHY: Duplicate orders on the same day suggest double-execution on repeated signals.
    """
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ticker, strategy, substr(timestamp, 1, 10) AS trade_date, COUNT(*) AS cnt
        FROM trades
        GROUP BY ticker, strategy, trade_date
        HAVING cnt > 1
        """
    )
    duplicates = cursor.fetchall()
    conn.close()

    if not duplicates:
        conn2 = sqlite3.connect(db.db_path)
        trade_count = conn2.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn2.close()
        if trade_count == 0:
            print_result("test_no_duplicate_orders_same_day", True, "no trades to check")
        else:
            print_result("test_no_duplicate_orders_same_day", True)
        assert True
        return

    detail = "; ".join(f"{t}/{s}/{d} x{c}" for t, s, d, c in duplicates)
    print_result("test_no_duplicate_orders_same_day", False, detail)
    assert False, f"Duplicate orders found: {detail}"


@pytest.mark.invariant
def test_every_fill_maps_to_real_order(db):
    """
    WHAT: Every trade with a fill status must have a non-null, non-empty order_id.
    WHY: Fills without order IDs break audit trails and reconciliation with Alpaca.
    """
    trades = db.get_all_trades()
    filled = [t for t in trades if (t.get("status") or "").lower() in FILL_STATUSES]

    if not filled:
        print_result("test_every_fill_maps_to_real_order", True, "no filled trades to check")
        return

    bad = [t for t in filled if not t.get("order_id") or not str(t["order_id"]).strip()]
    passed = len(bad) == 0
    detail = f"{len(bad)} fills missing order_id" if bad else f"{len(filled)} fills OK"
    print_result("test_every_fill_maps_to_real_order", passed, detail)
    assert passed, f"Fills without order_id: {bad}"


@pytest.mark.invariant
def test_position_cap_respected(db):
    """
    WHAT: No position entry value (qty * entry_price) exceeds $10k + 5% buffer.
    WHY: The executor caps buys at MAX_DOLLAR_PER_STOCK; violations mean sizing logic failed.
    """
    snapshot = get_latest_snapshot(db)
    if snapshot is None:
        flag("no portfolio snapshots in DB")

    positions_raw = snapshot[5]
    positions = json.loads(positions_raw) if positions_raw else {}
    open_positions = {t: float(q) for t, q in positions.items() if q}

    if not open_positions:
        print_result("test_position_cap_respected", True, "no open positions")
        return

    entry_prices = _get_entry_prices(db, list(open_positions.keys()))
    missing = [t for t in open_positions if t not in entry_prices]
    if missing:
        flag(f"no entry price for open position: {', '.join(missing)}")

    cap_limit = POSITION_CAP * CAP_BUFFER
    violations = []
    for ticker, qty in open_positions.items():
        entry_value = abs(qty) * entry_prices[ticker]
        if entry_value > cap_limit:
            violations.append(f"{ticker}: ${entry_value:,.2f} > ${cap_limit:,.2f}")

    passed = len(violations) == 0
    detail = "; ".join(violations) if violations else f"{len(open_positions)} positions within cap"
    print_result("test_position_cap_respected", passed, detail)
    assert passed, f"Position cap violated: {violations}"


@pytest.mark.invariant
def test_signals_are_valid_values():
    """
    WHAT: Every strategy's generate_signals output must be in {-1, 0, 1}.
    WHY: Invalid signal values would cause undefined behavior in the executor.
    """
    data = _make_synthetic_ohlcv()
    data_b = data.copy()
    data_b["Close"] = data["Close"] * 1.05
    data_b["Open"] = data["Open"] * 1.05
    data_b["High"] = data["High"] * 1.05
    data_b["Low"] = data["Low"] * 1.05

    momentum = MomentumStrategy(lookback_period=120)
    _assert_valid_signals(momentum.generate_signals(data), "Momentum")

    ma_cross = MeanReversionStrategy(short_window=50, long_window=200)
    _assert_valid_signals(ma_cross.generate_signals(data), "MA Crossover")

    stat_arb = StatArbStrategy("AAPL", "MSFT", lookback=60)
    sig_a, sig_b = stat_arb.generate_signals(data, data_b)
    _assert_valid_signals(sig_a, "Stat Arb (leg A)")
    _assert_valid_signals(sig_b, "Stat Arb (leg B)")

    print_result("test_signals_are_valid_values", True, "Momentum, MA Crossover, Stat Arb OK")
