"""
Pytest configuration for BackTrace.

Registers the `invariant` marker and prints a per-invariant summary at the end
of a run, so a failing invariant is legible without scrolling the full report.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Collect per-test outcomes for terminal summary
_invariant_results = []


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "invariant: a property that must hold for any backtest run",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    if not item.name.startswith("test_"):
        return
    if "invariant" not in item.keywords:
        return
    status = "pass" if report.passed else ("flag" if "FLAGGED" in str(report.longrepr or "") else "fail")
    _invariant_results.append({"name": item.name, "status": status})


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not _invariant_results:
        return

    counts = {"pass": 0, "fail": 0, "flag": 0}
    for r in _invariant_results:
        counts[r["status"]] += 1

    terminalreporter.write_sep("=", "INVARIANT SUMMARY")
    for r in _invariant_results:
        terminalreporter.write_line(f"  [{r['status'].upper()}] {r['name']}")
    terminalreporter.write_line(
        f"\n  Total: {len(_invariant_results)} | "
        f"Passed: {counts['pass']} | Failed: {counts['fail']} | Flagged: {counts['flag']}"
    )
    terminalreporter.write_sep("=", "")
