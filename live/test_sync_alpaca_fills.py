"""
Tests for sync_alpaca_fills.py's reconciliation logic, using a mocked Alpaca TradingClient
(no real API calls, no real DB). Verifies: missing orders get inserted, drifted status/price on
existing rows get updated, unchanged rows are left alone, and the whole thing is idempotent
(safe to re-run without creating duplicates).
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from database import Database
from sync_alpaca_fills import sync_fills, _normalize_status, _normalize_side


def get_test_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sync_fills_test_")
    os.close(fd)
    return path


def _mock_enum(value):
    """Mimic an alpaca-py enum member: has a lowercase .value, and str() looks like 'Enum.VALUE'."""
    m = MagicMock()
    m.value = value
    m.__str__.return_value = f"OrderStatus.{value.upper()}"
    return m


def _mock_order(order_id, symbol, side, status, filled_avg_price, qty=10, filled_qty=None,
                 filled_at="2026-08-01T13:30:00+00:00", submitted_at="2026-08-01T08:00:00+00:00"):
    order = MagicMock()
    order.id = order_id
    order.symbol = symbol
    order.side = _mock_enum(side)
    order.status = _mock_enum(status)
    order.filled_avg_price = filled_avg_price
    order.qty = str(qty)
    order.filled_qty = str(filled_qty) if filled_qty is not None else (str(qty) if status == "filled" else None)

    def _iso_mock(ts):
        if ts is None:
            return None
        dt = MagicMock()
        dt.isoformat.return_value = ts
        return dt

    order.filled_at = _iso_mock(filled_at)
    order.submitted_at = _iso_mock(submitted_at)
    order.created_at = _iso_mock(submitted_at)
    return order


def _mock_client(orders):
    """Mock TradingClient whose get_orders() always returns the full `orders` list in one page."""
    client = MagicMock()
    client.get_orders.return_value = list(orders)
    return client


# ---- unit tests for normalization helpers ----

def test_normalize_status_enum():
    """Enum-like status with .value normalizes to the lowercase value, not the 'OrderStatus.X' repr."""
    status = _mock_enum("filled")
    assert _normalize_status(status) == "filled"
    return True


def test_normalize_status_plain_string():
    """A plain 'OrderStatus.ACCEPTED'-style string (as currently stored by execute_signal) is stripped."""
    assert _normalize_status("OrderStatus.ACCEPTED") == "accepted"
    assert _normalize_status("PENDING_NEW") == "pending_new"
    return True


def test_normalize_side():
    side = _mock_enum("buy")
    assert _normalize_side(side) == "BUY"
    assert _normalize_side("sell") == "SELL"
    return True


# ---- integration tests for sync_fills() ----

def test_insert_missing_orders():
    """Orders on Alpaca with no local trades row get inserted, tagged with the reconciled label."""
    db_path = get_test_db_path()
    try:
        db = Database(db_path)
        orders = [
            _mock_order("order-1", "AAPL", "buy", "filled", "150.00", qty=10),
            _mock_order("order-2", "MSFT", "sell", "filled", "300.00", qty=5),
        ]
        client = _mock_client(orders)
        result = sync_fills(db=db, client=client)
        assert result["orders_seen"] == 2, result
        assert result["inserted"] == 2, result
        assert result["updated"] == 0, result
        assert result["total_trades"] == 2, result

        trades = db.get_all_trades()
        assert len(trades) == 2
        by_order = {t["order_id"]: t for t in trades}
        assert by_order["order-1"]["status"] == "filled"
        assert by_order["order-1"]["price"] == 150.0
        assert by_order["order-1"]["ticker"] == "AAPL"
        assert by_order["order-1"]["side"] == "BUY"
        assert by_order["order-2"]["side"] == "SELL"
        assert "Unknown" in by_order["order-1"]["strategy"]
        return True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_update_drifted_existing_row():
    """A trade row logged at submission time (PENDING_NEW, estimated price) gets updated once
    Alpaca reports the real fill status/price -- this is the core bug being fixed."""
    db_path = get_test_db_path()
    try:
        db = Database(db_path)
        # Simulate what execute_signal() logs today: submission-time status + estimated price.
        db.log_trade(strategy="Momentum", ticker="AAPL", side="BUY", qty=10,
                     price=149.50, order_id="order-1", status="OrderStatus.PENDING_NEW")

        orders = [_mock_order("order-1", "AAPL", "buy", "filled", "150.25", qty=10)]
        client = _mock_client(orders)
        result = sync_fills(db=db, client=client)
        assert result["updated"] == 1, result
        assert result["inserted"] == 0, result
        assert result["total_trades"] == 1, result

        trades = db.get_all_trades()
        assert len(trades) == 1
        assert trades[0]["status"] == "filled"
        assert trades[0]["price"] == 150.25
        # Strategy is untouched by an UPDATE (only status/price change) -- real attribution is preserved.
        assert trades[0]["strategy"] == "Momentum"
        return True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_unchanged_row_not_touched():
    """A row that already matches Alpaca's current status/price is left alone (counted unchanged)."""
    db_path = get_test_db_path()
    try:
        db = Database(db_path)
        db.log_trade(strategy="Momentum", ticker="AAPL", side="BUY", qty=10,
                     price=150.0, order_id="order-1", status="filled")
        orders = [_mock_order("order-1", "AAPL", "buy", "filled", "150.0", qty=10)]
        client = _mock_client(orders)
        result = sync_fills(db=db, client=client)
        assert result["updated"] == 0, result
        assert result["unchanged"] == 1, result
        assert result["inserted"] == 0, result
        return True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_idempotent_second_run():
    """Running sync_fills twice in a row produces no further changes and no duplicate rows."""
    db_path = get_test_db_path()
    try:
        db = Database(db_path)
        orders = [
            _mock_order("order-1", "AAPL", "buy", "filled", "150.00"),
            _mock_order("order-2", "MSFT", "sell", "filled", "300.00"),
        ]
        client = _mock_client(orders)
        first = sync_fills(db=db, client=client)
        assert first["inserted"] == 2

        second = sync_fills(db=db, client=client)
        assert second["inserted"] == 0, second
        assert second["updated"] == 0, second
        assert second["unchanged"] == 2, second
        assert second["total_trades"] == 2, second
        assert len(db.get_all_trades()) == 2
        return True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_missing_keys_returns_error():
    """sync_fills() reports a clear error dict (not an exception) when Alpaca keys are missing,
    matching the graceful-fallback pattern used elsewhere in this codebase."""
    from sync_alpaca_fills import sync_fills as sf
    db_path = get_test_db_path()
    try:
        db = Database(db_path)
        result = sf(db=db, client=None)
        # With client=None and no env keys set in this process, _get_client() should return None.
        # (If ALPACA_API_KEY happens to be set in the environment, this becomes a live call instead --
        # so only assert the error path when keys are genuinely absent.)
        if not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_SECRET_KEY"):
            assert "error" in result, result
        return True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def main():
    print("=" * 60)
    print("SYNC_ALPACA_FILLS TEST REPORT (mocked Alpaca client)")
    print("=" * 60)
    tests = [
        ("normalize_status: enum", test_normalize_status_enum),
        ("normalize_status: plain string", test_normalize_status_plain_string),
        ("normalize_side", test_normalize_side),
        ("insert missing orders", test_insert_missing_orders),
        ("update drifted existing row", test_update_drifted_existing_row),
        ("unchanged row not touched", test_unchanged_row_not_touched),
        ("idempotent second run", test_idempotent_second_run),
        ("missing keys returns error", test_missing_keys_returns_error),
    ]
    report = []
    for name, fn in tests:
        try:
            fn()
            report.append((name, True, None))
        except Exception as e:
            report.append((name, False, str(e)))

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
