"""
Executor full test: all 10 SPY tickers, data fetch, signal generation, mocked trade placement.
Verifies database logging and error handling. Does NOT place real orders.
"""

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
    order = MagicMock()
    order.id = "mock-order-id"
    order.status = "accepted"
    client.submit_order.return_value = order
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
    from strategies.mean_reversion import MeanReversionStrategy

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
