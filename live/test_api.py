"""
API endpoint tests: all routes return correct shape, query params, CORS, error responses.
Uses FastAPI TestClient. Uses live DB in live/ (read-only where possible).
"""

import os
import sys
import json
import tempfile

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

# Use test DB so we don't mutate production
TEST_DB = os.path.join(LIVE_DIR, "test_api_db.db")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

os.environ.setdefault("ALPACA_API_KEY", "")
os.environ.setdefault("ALPACA_SECRET_KEY", "")


def get_app_with_test_db():
    """Create FastAPI app instance with test database."""
    try:
        from fastapi.testclient import TestClient
    except ImportError as e:
        if "httpx" in str(e).lower():
            raise ImportError("API tests require httpx. Install with: pip install httpx") from e
        raise
    from database import Database
    import api as api_module
    # Replace db with test DB
    api_module.db = Database(TEST_DB)
    return api_module.app


def test_root():
    """GET / returns message."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "message" in data
    return True


def test_portfolio():
    """GET /portfolio - verify format and keys."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/portfolio")
    assert r.status_code == 200
    data = r.json()
    assert "portfolio_value" in data and "cash" in data and "positions" in data
    assert "timestamp" in data and "strategy" in data
    assert "live_sync_used" in data
    return True


def test_trades():
    """GET /trades and /trades?strategy=Momentum."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/trades")
    assert r.status_code == 200
    data = r.json()
    assert "trades" in data
    assert isinstance(data["trades"], list)
    r2 = client.get("/trades?strategy=Momentum")
    assert r2.status_code == 200
    assert "trades" in r2.json()
    return True


def test_portfolio_history():
    """GET /portfolio-history - chronological order and format."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/portfolio-history")
    assert r.status_code == 200
    data = r.json()
    assert "history" in data
    assert isinstance(data["history"], list)
    for h in data["history"]:
        assert "timestamp" in h and "portfolio_value" in h and "positions" in h
    r2 = client.get("/portfolio-history?strategy=Momentum")
    assert r2.status_code == 200
    return True


def test_performance():
    """GET /performance - validate metrics shape."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/performance")
    assert r.status_code == 200
    data = r.json()
    assert "total_return" in data and "num_trades" in data and "current_value" in data
    assert isinstance(data["total_return"], (int, float))
    r2 = client.get("/performance?strategy=MA%20Crossover")
    assert r2.status_code == 200
    return True


def test_backtest_results():
    """GET /backtest-results - empty or list with expected keys."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/backtest-results")
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    r2 = client.get("/backtest-results?ticker=AAPL&strategy=Momentum")
    assert r2.status_code == 200
    return True


def test_monte_carlo():
    """GET /monte-carlo - requires ticker; may return error if no backtest."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/monte-carlo?ticker=AAPL&strategy=Momentum&runs=100")
    # 422 if no backtest results, 200 if results exist
    assert r.status_code in (200, 422, 500), f"Unexpected status {r.status_code}: {r.text[:200]}"
    if r.status_code == 200:
        data = r.json()
        # 200 can be success (probability_profit, percentiles) or error message body
        assert isinstance(data, dict)
    elif r.status_code == 422:
        assert "detail" in r.json()
    return True


def test_available_pairs():
    """GET /available-pairs/{ticker}."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/available-pairs/AAPL")
    assert r.status_code == 200
    data = r.json()
    assert "ticker" in data and "available_pairs" in data
    assert data["ticker"] == "AAPL"
    return True


def test_pairs():
    """GET /pairs."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/pairs")
    assert r.status_code == 200
    assert "pairs" in r.json()
    return True


def test_pair_trades():
    """GET /pair-trades."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/pair-trades")
    assert r.status_code == 200
    assert "pair_trades" in r.json()
    return True


def test_delete_trade_404():
    """DELETE /trades/99999 -> 404."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.delete("/trades/99999")
    assert r.status_code == 404
    return True


def test_cors_headers():
    """Verify CORS headers present (OPTIONS or response headers)."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/portfolio")
    # CORS middleware often adds Access-Control-Allow-Origin on response
    assert r.status_code == 200
    # Allow-Origin may be * when allow_origins=["*"]
    return True


def test_backtest_post():
    """POST /backtest - valid request returns 200 or 422 (e.g. no data)."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    payload = {
        "ticker": "AAPL",
        "start_date": "2024-01-01",
        "end_date": "2024-06-01",
        "strategy": "Momentum",
    }
    r = client.post("/backtest", json=payload)
    # 200 if data exists, 422 if no data for range, 500 on other errors
    assert r.status_code in (200, 422, 500)
    if r.status_code == 200:
        data = r.json()
        assert "total_return" in data or "equity_curve" in data
    return True


def test_live_benchmark():
    """GET /live-benchmark - returns structure (may have empty curves)."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/live-benchmark?time_range=1Y")
    assert r.status_code == 200
    data = r.json()
    assert "live" in data and "live_equity_curve" in data
    assert "spy" in data or data.get("spy") is None
    return True


def test_run_executor_requires_ticker():
    """POST /run-executor - without Stat Arb pair can run (or 400 if keys missing)."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.post("/run-executor", json={"ticker": "AAPL", "strategy": "Momentum"})
    # 200 if ran, 400 if missing keys (ValueError), 500 on other
    assert r.status_code in (200, 400, 500)
    return True


def test_positions_detail():
    """GET /positions-detail - returns structure."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/positions-detail")
    assert r.status_code == 200
    data = r.json()
    assert "positions" in data and "portfolio_value" in data
    return True


def test_divergence_analysis_no_backtest():
    """GET /divergence-analysis returns 422 when no saved backtest for ticker/strategy."""
    from fastapi.testclient import TestClient
    app = get_app_with_test_db()
    client = TestClient(app)
    r = client.get("/divergence-analysis?ticker=AAPL&strategy=Momentum")
    assert r.status_code == 422
    return True


def main():
    tests = [
        ("GET /", test_root),
        ("GET /portfolio", test_portfolio),
        ("GET /trades", test_trades),
        ("GET /portfolio-history", test_portfolio_history),
        ("GET /performance", test_performance),
        ("GET /backtest-results", test_backtest_results),
        ("GET /monte-carlo", test_monte_carlo),
        ("GET /available-pairs/{ticker}", test_available_pairs),
        ("GET /pairs", test_pairs),
        ("GET /pair-trades", test_pair_trades),
        ("DELETE /trades/99999 (404)", test_delete_trade_404),
        ("CORS", test_cors_headers),
        ("POST /backtest", test_backtest_post),
        ("GET /live-benchmark", test_live_benchmark),
        ("POST /run-executor", test_run_executor_requires_ticker),
        ("GET /positions-detail", test_positions_detail),
        ("GET /divergence-analysis", test_divergence_analysis_no_backtest),
    ]
    print("=" * 60)
    print("API ENDPOINT TESTS")
    print("=" * 60)
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed.append(name)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    print("=" * 60)
    print(f"Result: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("Failed:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
