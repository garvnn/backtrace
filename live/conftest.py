"""
Pytest configuration for BackTrace live invariant tests.
"""

import os
import sys

import pytest

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from database import Database

PRODUCTION_DB = os.path.join(LIVE_DIR, "trading.db")

# Collect per-test outcomes for terminal summary
_invariant_results = []


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "invariant: portfolio/system invariant check",
    )


@pytest.fixture(scope="session")
def db():
    """
    Database connected to DB_PATH (test DB written by executor).
    Fails fast if DB_PATH is unset or points at production without override.
    """
    db_path = os.environ.get("DB_PATH")
    if not db_path:
        pytest.fail(
            "DB_PATH is not set. Export a non-production test database path, e.g.\n"
            "  export DB_PATH=/tmp/backtrace_invariant_test.db"
        )

    db_path = os.path.abspath(db_path)
    if db_path == os.path.abspath(PRODUCTION_DB) and os.environ.get("INVARIANT_ALLOW_PRODUCTION") != "1":
        pytest.fail(
            f"DB_PATH points to production database ({PRODUCTION_DB}). "
            "Set INVARIANT_ALLOW_PRODUCTION=1 to override."
        )

    return Database(db_path)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    if not item.name.startswith("test_"):
        return
    status = "pass" if report.passed else ("flag" if "FLAGGED" in str(report.longrepr or "") else "fail")
    _invariant_results.append(
        {
            "name": item.name,
            "status": status,
            "detail": str(report.longrepr) if report.failed else "",
        }
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not _invariant_results:
        return

    passed = sum(1 for r in _invariant_results if r["status"] == "pass")
    failed = sum(1 for r in _invariant_results if r["status"] == "fail")
    flagged = sum(1 for r in _invariant_results if r["status"] == "flag")

    terminalreporter.write_sep("=", "INVARIANT TEST SUMMARY")
    for r in _invariant_results:
        label = r["status"].upper()
        terminalreporter.write_line(f"  [{label}] {r['name']}")
    terminalreporter.write_line(
        f"\n  Total: {len(_invariant_results)} | Passed: {passed} | Failed: {failed} | Flagged: {flagged}"
    )
    terminalreporter.write_sep("=", "")
