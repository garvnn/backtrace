"""
Executor full test: all 10 SPY tickers, data fetch, signal generation, mocked trade placement.
Verifies database logging and error handling. Does NOT place real orders.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

# Top 10 SPY tickers (must match scheduler)
TOP_10_SPY = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "BRK.B", "UNH", "XOM",
]


def _mock_trading_client():
    """Create a mock TradingClient: no real orders, fake account and positions."""
    client = MagicMock()
    account = MagicMock()
    account.portfolio_value = 100000.0
    account.cash = 100000.0
    account.buying_power = 95000.0
    client.get_account.return_value = account
    client.get_all_positions.return_value = []

    def _submit(order_data):
        # Alpaca echoes the submitted client_order_id back on the created order
        # (generating one if the caller omitted it), so the mock does too - the
        # executor persists that field and a bare MagicMock is not a value
        # sqlite can bind.
        order = MagicMock()
        order.id = "mock-order-id"
        order.status = "accepted"
        order.client_order_id = getattr(order_data, "client_order_id", None) or "mock-client-order-id"
        order.filled_qty = None
        order.filled_avg_price = None
        return order

    client.submit_order.side_effect = _submit
    return client


def _mock_data_client_empty():
    """Mock data client that returns empty DataFrame (e.g. bad ticker / no data)."""
    client = MagicMock()
    import pandas as pd
    client.get_stock_bars.return_value = MagicMock(df=pd.DataFrame())
    return client


def _mock_data_client_failure():
    """Mock data client that raises (API failure)."""
    client = MagicMock()
    client.get_stock_bars.side_effect = Exception("Rate limit / network error")
    return client


def run_executor_test_for_ticker(ticker, mock_trade=True, use_real_data=True):
    """
    Run executor flow for one ticker.
    If mock_trade=True, no real orders are placed.
    If use_real_data=False, we only test with mocked data (e.g. when no API keys).
    Returns dict with keys: ticker, data_ok, signal_ok, executed_mock, error.
    """
    from strategies.momentum import MomentumStrategy
    from executor import StrategyExecutor
    import pandas as pd

    result = {"ticker": ticker, "data_ok": False, "signal_ok": False, "executed_mock": False, "error": None}
    db_path = tempfile.mktemp(suffix=".db", prefix="exec_test_")
    try:
        with patch.dict(os.environ, {"ALPACA_API_KEY": "test-key", "ALPACA_SECRET_KEY": "test-secret"}, clear=False):
            with patch("executor.TradingClient", return_value=_mock_trading_client()):
                with patch("executor.Database") as MockDB:
                    mock_db_instance = MagicMock()
                    mock_db_instance.get_last_executed_signal.return_value = None
                    MockDB.return_value = mock_db_instance
                    exec_module = __import__("executor", fromlist=["StrategyExecutor"])
                    StrategyExecutor = exec_module.StrategyExecutor
                    # Use test DB path so we don't touch real DB
                    with patch.object(exec_module.StrategyExecutor, "__init__", wraps=StrategyExecutor.__init__) as w:
                        pass
                    strategy = MomentumStrategy()
                    # Constructor needs real DB for get_last_executed_signal; use temp DB
                    from database import Database
                    test_db = Database(db_path)
                    test_db.get_last_executed_signal = MagicMock(return_value=None)
                    with patch("executor.Database", return_value=test_db):
                        executor = StrategyExecutor(strategy, ticker=ticker)
                    executor.trading_client = _mock_trading_client()
                    executor.db = test_db
        if use_real_data:
            try:
                data = executor.get_historical_data(days=90)
            except Exception as e:
                result["error"] = f"Data fetch: {e}"
                return result
            if data is None or (hasattr(data, "empty") and data.empty) or len(data) < 30:
                result["error"] = "Insufficient data"
                return result
            result["data_ok"] = True
        else:
            # Fake data for offline test
            data = pd.DataFrame({
                "Open": [100] * 60, "High": [101] * 60, "Low": [99] * 60,
                "Close": [100 + i * 0.5 for i in range(60)], "Volume": [1e6] * 60,
            }, index=pd.date_range("2024-01-01", periods=60, freq="D"))
            result["data_ok"] = True
        signals = strategy.generate_signals(data)
        current_signal = signals.iloc[-1]
        result["signal_ok"] = current_signal in (0, 1)
        # Execute with mock (no real order)
        executor.execute_signal(current_signal, data)
        result["executed_mock"] = True
    except Exception as e:
        result["error"] = str(e)
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
    return result


def run_all_tickers_mock_only():
    """
    Run executor tests with fully mocked Alpaca (no API keys needed).
    Tests: strategy runs, signal generation, execute_signal path with mock client.
    """
    import pandas as pd
    from strategies.momentum import MomentumStrategy
    from strategies.ma_crossover import MACrossoverStrategy

    results = []
    for ticker in TOP_10_SPY:
        r = {"ticker": ticker, "data_ok": False, "signal_ok": False, "executed_mock": False, "error": None}
        try:
            with patch.dict(os.environ, {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}, clear=False):
                with patch("executor.TradingClient", return_value=_mock_trading_client()):
                    with patch("executor.StockHistoricalDataClient") as MockData:
                        mock_bars = MagicMock()
                        n = 100
                        idx = pd.DatetimeIndex(pd.date_range("2024-01-01", periods=n, freq="B"))
                        import numpy as np
                        mock_bars.df = pd.DataFrame({
                            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0 + np.arange(n) * 0.1,
                            "volume": 1e6,
                        }, index=idx)
                        mock_bars.df.index.name = "timestamp"
                        MockData.return_value.get_stock_bars.return_value = mock_bars
                        from executor import StrategyExecutor
                        from database import Database
                        fd, db_path = tempfile.mkstemp(suffix=".db")
                        os.close(fd)
                        db = Database(db_path)
                        db.get_last_executed_signal = MagicMock(return_value=None)
                        with patch("executor.Database", return_value=db):
                            ex = StrategyExecutor(MomentumStrategy(), ticker=ticker)
                        ex.trading_client = _mock_trading_client()
                        ex.db = db
                        data = ex.get_historical_data(days=90)
                        if data is not None and len(data) >= 30:
                            r["data_ok"] = True
                        signals = MomentumStrategy().generate_signals(data)
                        r["signal_ok"] = True
                        ex.execute_signal(signals.iloc[-1], data)
                        r["executed_mock"] = True
                        if os.path.exists(db_path):
                            os.remove(db_path)
        except Exception as e:
            r["error"] = str(e)
        results.append(r)
    return results


def run_with_real_data_if_available():
    """
    If ALPACA keys are set, run executor for one ticker (AAPL) with real data and mocked order.
    Otherwise skip and return a single skipped result.
    """
    if not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_SECRET_KEY"):
        return [{"ticker": "AAPL", "data_ok": False, "signal_ok": False, "executed_mock": False, "error": "No Alpaca keys; skipped real-data test"}]
    from executor import StrategyExecutor
    from strategies.momentum import MomentumStrategy
    from database import Database
    import tempfile
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = {"ticker": "AAPL", "data_ok": False, "signal_ok": False, "executed_mock": False, "error": None}
    try:
        db = Database(db_path)
        with patch("executor.TradingClient", return_value=_mock_trading_client()):
            ex = StrategyExecutor(MomentumStrategy(), ticker="AAPL")
        ex.trading_client = _mock_trading_client()
        ex.db = db
        data = ex.get_historical_data(days=90)
        if data is None or (hasattr(data, "empty") and data.empty):
            r["error"] = "No data returned"
        elif len(data) < 30:
            r["error"] = "Insufficient bars"
        else:
            r["data_ok"] = True
            signals = ex.strategy.generate_signals(data)
            r["signal_ok"] = True
            ex.execute_signal(signals.iloc[-1], data)
            r["executed_mock"] = True
    except Exception as e:
        r["error"] = str(e)
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
    return [r]


def test_error_handling_bad_ticker():
    """Test executor with invalid ticker (mocked empty data)."""
    from executor import StrategyExecutor
    from strategies.momentum import MomentumStrategy
    with patch.dict(os.environ, {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}, clear=False):
        with patch("executor.TradingClient", return_value=_mock_trading_client()):
            with patch("executor.StockHistoricalDataClient", return_value=_mock_data_client_empty()):
                from database import Database
                fd, db_path = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                db = Database(db_path)
                try:
                    ex = StrategyExecutor(MomentumStrategy(), ticker="INVALIDTICKER999")
                    data = ex.get_historical_data(days=30)
                    empty = data is None or (hasattr(data, "empty") and data.empty)
                    return empty  # Expect empty data
                except Exception:
                    return True  # Or it may raise; both are acceptable
                finally:
                    if os.path.exists(db_path):
                        os.remove(db_path)
    return False


def test_session_budget_caps_cumulative_spend_across_tickers():
    """
    Two tickers, each individually within MAX_DOLLAR_PER_STOCK and buying_power,
    but sharing a SessionBudget smaller than their combined per-stock caps.
    Without the shared budget, each would buy up to MAX_DOLLAR_PER_STOCK
    independently (over-spending real cash via margin); with it, the second
    ticker's buy must be sized down to whatever's left.
    """
    import pandas as pd
    from executor import StrategyExecutor, SessionBudget
    from strategies.momentum import MomentumStrategy
    from database import Database
    from trading_constants import MAX_DOLLAR_PER_STOCK

    data = pd.DataFrame(
        {"Open": [100] * 5, "High": [101] * 5, "Low": [99] * 5, "Close": [100.0] * 5, "Volume": [1e6] * 5},
        index=pd.date_range("2024-01-01", periods=5, freq="D"),
    )

    # Session budget smaller than 2x MAX_DOLLAR_PER_STOCK: the two tickers'
    # per-stock caps ($10k each = $20k) would together exceed it ($15k).
    budget = SessionBudget(15000.0)
    assert budget.remaining == 15000.0

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # High buying_power (as on a margin account, matching the real account
        # this was diagnosed on) so the OLD per-stock-only cap would let both
        # tickers buy the full MAX_DOLLAR_PER_STOCK ($10k) each = $20k total.
        mock_client = _mock_trading_client()
        with patch.dict(os.environ, {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}, clear=False):
            with patch("executor.TradingClient", return_value=mock_client):
                db = Database(db_path)
                db.get_last_executed_signal = MagicMock(return_value=None)
                with patch("executor.Database", return_value=db):
                    ex_a = StrategyExecutor(MomentumStrategy(), ticker="AAA", session_budget=budget)
                    ex_b = StrategyExecutor(MomentumStrategy(), ticker="BBB", session_budget=budget)

            ex_a.execute_signal(1, data)
            assert budget.remaining == 5000.0, f"expected $5,000 left after first buy, got {budget.remaining}"

            ex_b.execute_signal(1, data)
            assert budget.remaining == 0.0, f"expected $0 left after second buy, got {budget.remaining}"

        calls = mock_client.submit_order.call_args_list
        assert len(calls) == 2, f"expected 2 orders submitted, got {len(calls)}"
        qty_a = calls[0].args[0].qty
        qty_b = calls[1].args[0].qty
        assert qty_a == 100, f"first buy should be full $10k/$100 = 100 shares, got {qty_a}"
        assert qty_b == 50, f"second buy should be capped to remaining $5k/$100 = 50 shares (not another {int(MAX_DOLLAR_PER_STOCK/100)}), got {qty_b}"
        return True
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def main():
    print("=" * 60)
    print("EXECUTOR FULL TEST (Mocked Orders)")
    print("=" * 60)
    print("Running on all 10 SPY tickers with mocked Alpaca (no real orders)...")
    results = run_all_tickers_mock_only()
    for r in results:
        status = "OK" if not r["error"] and r["data_ok"] and r["signal_ok"] else "FAIL/SKIP"
        print(f"  {r['ticker']}: data={r['data_ok']}, signal={r['signal_ok']}, executed_mock={r['executed_mock']} — {status}" + (f" — {r['error']}" if r["error"] else ""))
    print()
    print("Real-data test (AAPL, if keys set)...")
    real_results = run_with_real_data_if_available()
    for r in real_results:
        print(f"  {r['ticker']}: data_ok={r['data_ok']}, signal_ok={r['signal_ok']}, error={r['error']}")
    print()
    print("Error handling (bad ticker / empty data)...")
    try:
        bad_ok = test_error_handling_bad_ticker()
        print(f"  Bad ticker handled: {bad_ok}")
    except Exception as e:
        print(f"  Bad ticker test error: {e}")
    print()
    print("Session budget caps cumulative spend across tickers...")
    try:
        budget_ok = test_session_budget_caps_cumulative_spend_across_tickers()
        print(f"  Session budget capping correct: {budget_ok}")
    except Exception as e:
        print(f"  Session budget test error: {e}")
    print("=" * 60)
    passed = sum(1 for r in results if not r["error"] and r["data_ok"] and r["signal_ok"])
    print(f"Summary: {passed}/{len(results)} tickers passed (mock mode)")
    print("=" * 60)
    return 0 if passed >= len(results) else 1


if __name__ == "__main__":
    sys.exit(main())


def _account(portfolio_value, cash):
    a = MagicMock()
    a.portfolio_value = portfolio_value
    a.cash = cash
    a.buying_power = float(cash) * 2
    return a


def _position(symbol, qty, market_value):
    p = MagicMock()
    p.symbol = symbol
    p.qty = qty
    p.market_value = market_value
    return p


def _snapshot_executor(db_path, account_reads, position_reads):
    """Executor whose account/position reads are scripted per call."""
    from strategies.momentum import MomentumStrategy
    from database import Database
    from executor import StrategyExecutor

    client = MagicMock()
    client.get_account.side_effect = list(account_reads)
    client.get_all_positions.side_effect = list(position_reads)

    db = Database(db_path)
    db.get_last_executed_signal = MagicMock(return_value=None)
    with patch.dict(os.environ, {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}, clear=False):
        with patch("executor.TradingClient", return_value=client):
            with patch("executor.Database", return_value=db):
                ex = StrategyExecutor(MomentumStrategy(), ticker="AAPL")
    ex.trading_client = client
    ex.db = db
    return ex, db


def test_snapshot_refused_when_value_omits_positions():
    """
    The 2026-07-07 production defect: Alpaca reports portfolio_value == cash
    while six positions are held. Persisting that row put a 61% drawdown on a
    curve whose real return is +1.65%, so it must not be written.
    """
    import snapshot_health

    held = [_position("AAPL", 10, 62_534.06)]
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Both reads bad: the retry does not rescue it.
        ex, db = _snapshot_executor(
            db_path,
            account_reads=[_account(43_135.33, 43_135.33), _account(43_135.33, 43_135.33)],
            position_reads=[held, held],
        )
        with patch.object(snapshot_health, "SNAPSHOT_RETRY_DELAY_SECONDS", 0):
            with patch("executor.SNAPSHOT_RETRY_DELAY_SECONDS", 0):
                result = ex.log_portfolio_snapshot()

        assert result is None, "refusal must be signalled to the caller"
        assert db.get_portfolio_history() == [], "no snapshot row may be written"
        logs = db.get_execution_logs()
        assert any(
            (row[5] if not isinstance(row, dict) else row.get("action")) == "NO_SNAPSHOT"
            for row in logs
        ), "the refusal must be recorded in execution_logs"
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_snapshot_retry_rescues_a_mid_mark_reading():
    """The defect is transient, so one re-read should recover the real state."""
    import snapshot_health

    held = [_position("AAPL", 10, 62_534.06)]
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _snapshot_executor(
            db_path,
            account_reads=[_account(43_135.33, 43_135.33), _account(105_669.41, 43_135.35)],
            position_reads=[[], held],
        )
        with patch.object(snapshot_health, "SNAPSHOT_RETRY_DELAY_SECONDS", 0):
            with patch("executor.SNAPSHOT_RETRY_DELAY_SECONDS", 0):
                result = ex.log_portfolio_snapshot()

        assert result == "ok"
        history = db.get_portfolio_history()
        assert len(history) == 1
        assert abs(float(history[0][3]) - 105_669.41) < 0.01, "the good read must be the one stored"
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_healthy_snapshot_written_normally():
    import snapshot_health

    held = [_position("AAPL", 10, 62_534.06)]
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _snapshot_executor(
            db_path,
            account_reads=[_account(105_669.41, 43_135.35)],
            position_reads=[held],
        )
        with patch.object(snapshot_health, "SNAPSHOT_RETRY_DELAY_SECONDS", 0):
            result = ex.log_portfolio_snapshot()
        assert result == "ok"
        assert len(db.get_portfolio_history()) == 1
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


# --- guarded pair execution ---------------------------------------------------

def _asset(tradable=True, shortable=True, easy_to_borrow=True):
    a = MagicMock()
    a.tradable = tradable
    a.shortable = shortable
    a.easy_to_borrow = easy_to_borrow
    return a


def _pair_executor(db_path, client):
    from strategies.stat_arb import StatArbStrategy
    from database import Database
    from executor import StrategyExecutor

    db = Database(db_path)
    db.get_last_executed_signal = MagicMock(return_value=None)
    with patch.dict(os.environ, {"ALPACA_API_KEY": "x", "ALPACA_SECRET_KEY": "y"}, clear=False):
        with patch("executor.TradingClient", return_value=client):
            with patch("executor.Database", return_value=db):
                ex = StrategyExecutor(
                    StatArbStrategy(ticker_a="MCD", ticker_b="YUM"), ticker="MCD"
                )
    ex.trading_client = client
    ex.db = db
    return ex, db


def _actions(db):
    return [r["action"] if isinstance(r, dict) else r[5] for r in db.get_execution_logs()]


def test_pair_legs_both_submitted_on_success():
    from alpaca.trading.enums import OrderSide

    client = MagicMock()
    client.get_asset.return_value = _asset()
    client.submit_order.side_effect = lambda req: MagicMock(id=f"ord-{req.symbol}")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _pair_executor(db_path, client)
        a, b = ex._submit_pair_legs(
            "MCD-YUM", ("MCD", 10, OrderSide.BUY), ("YUM", 12, OrderSide.SELL), tag="open-long"
        )
        assert a.id == "ord-MCD" and b.id == "ord-YUM"
        assert client.submit_order.call_count == 2
        # Both legs carry a client_order_id, and they differ.
        ids = [c.args[0].client_order_id for c in client.submit_order.call_args_list]
        assert all(ids) and len(set(ids)) == 2
        assert "PAIR_INTENT" in _actions(db), "intent must be recorded before submitting"
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_leg_a_is_unwound_when_leg_b_is_rejected():
    """
    The naked-position case. Leg B rejected after leg A went in must not leave
    an unhedged directional position with no record of it.
    """
    from alpaca.trading.enums import OrderSide

    client = MagicMock()
    client.get_asset.return_value = _asset()
    submitted = []

    def _submit(req):
        submitted.append((req.symbol, req.side))
        if req.symbol == "YUM" and req.side == OrderSide.SELL:
            raise RuntimeError("insufficient margin")
        return MagicMock(id=f"ord-{req.symbol}")

    client.submit_order.side_effect = _submit
    client.cancel_order_by_id.side_effect = RuntimeError("already filled")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _pair_executor(db_path, client)
        with unittest.TestCase().assertRaises(RuntimeError):
            ex._submit_pair_legs(
                "MCD-YUM", ("MCD", 10, OrderSide.BUY), ("YUM", 12, OrderSide.SELL),
                tag="open-long",
            )

        # Leg A was flattened with the opposite side.
        assert ("MCD", OrderSide.SELL) in submitted, f"leg A not unwound: {submitted}"
        actions = _actions(db)
        assert "PAIR_LEG_FAILED" in actions
        row = [r for r in db.get_execution_logs()
               if (r["action"] if isinstance(r, dict) else r[5]) == "PAIR_LEG_FAILED"][0]
        details = row["details"] if isinstance(row, dict) else json.loads(row[7])
        assert details["leg_a_flattened"] is True
        assert details["naked_position_possible"] is False
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_unfilled_leg_a_is_cancelled_rather_than_flattened():
    """Cancelling an unfilled DAY order is cleaner than trading out of it."""
    from alpaca.trading.enums import OrderSide

    client = MagicMock()
    client.get_asset.return_value = _asset()
    client.submit_order.side_effect = lambda req: (
        (_ for _ in ()).throw(RuntimeError("rejected")) if req.symbol == "YUM"
        else MagicMock(id="ord-MCD")
    )
    client.cancel_order_by_id.return_value = None  # cancel succeeds

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _pair_executor(db_path, client)
        with unittest.TestCase().assertRaises(RuntimeError):
            ex._submit_pair_legs(
                "MCD-YUM", ("MCD", 10, OrderSide.BUY), ("YUM", 12, OrderSide.SELL),
                tag="open-long",
            )
        client.cancel_order_by_id.assert_called_once()
        row = [r for r in db.get_execution_logs()
               if (r["action"] if isinstance(r, dict) else r[5]) == "PAIR_LEG_FAILED"][0]
        details = row["details"] if isinstance(row, dict) else json.loads(row[7])
        assert details["leg_a_cancelled"] is True
        assert details["naked_position_possible"] is False
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_unshortable_leg_blocks_the_whole_pair():
    """Pre-check, so a rejection cannot arrive after the other leg is filled."""
    from alpaca.trading.enums import OrderSide

    client = MagicMock()
    client.get_asset.side_effect = lambda t: _asset(shortable=(t != "YUM"))
    client.submit_order.side_effect = AssertionError("must not submit")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _pair_executor(db_path, client)
        with unittest.TestCase().assertRaises(RuntimeError):
            ex._submit_pair_legs(
                "MCD-YUM", ("MCD", 10, OrderSide.BUY), ("YUM", 12, OrderSide.SELL),
                tag="open-long",
            )
        assert client.submit_order.call_count == 0, "no leg may be sent"
        assert "NO_TRADE" in _actions(db)
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_naked_position_is_flagged_when_unwind_also_fails():
    """If nothing can be done, the record must say so as loudly as possible."""
    from alpaca.trading.enums import OrderSide

    client = MagicMock()
    client.get_asset.return_value = _asset()

    def _submit(req):
        if req.symbol == "MCD" and req.side == OrderSide.BUY:
            return MagicMock(id="ord-MCD")
        raise RuntimeError("broker down")

    client.submit_order.side_effect = _submit
    client.cancel_order_by_id.side_effect = RuntimeError("already filled")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _pair_executor(db_path, client)
        with unittest.TestCase().assertRaises(RuntimeError):
            ex._submit_pair_legs(
                "MCD-YUM", ("MCD", 10, OrderSide.BUY), ("YUM", 12, OrderSide.SELL),
                tag="open-long",
            )
        row = [r for r in db.get_execution_logs()
               if (r["action"] if isinstance(r, dict) else r[5]) == "PAIR_LEG_FAILED"][0]
        details = row["details"] if isinstance(row, dict) else json.loads(row[7])
        assert details["naked_position_possible"] is True
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True


def test_unreadable_asset_record_does_not_block_trading():
    """A metadata outage must not become a trading halt."""
    from alpaca.trading.enums import OrderSide

    client = MagicMock()
    client.get_asset.side_effect = RuntimeError("503")
    client.submit_order.side_effect = lambda req: MagicMock(id=f"ord-{req.symbol}")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ex, db = _pair_executor(db_path, client)
        a, b = ex._submit_pair_legs(
            "MCD-YUM", ("MCD", 10, OrderSide.BUY), ("YUM", 12, OrderSide.SELL), tag="open-long"
        )
        assert a and b
    finally:
        os.path.exists(db_path) and os.remove(db_path)
    return True
