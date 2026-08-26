"""
Which saved backtest the live curve is compared against.

Regression cover for the bug these tests were written from: production held 27
saved runs of Momentum/AAPL over the same window reporting three different
total returns (+29.65% and +3.84%, all at n=49) because the sizing code changed
between them, and /divergence-analysis compared live performance against
results[0] - whichever row happened to sort first. An arbitrary database row
was setting the magnitude of the project's headline number.

test_stale_only_is_refused is the one that fails against the old behaviour.
"""

import os
import sys

import pytest

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

os.environ.setdefault("ALPACA_API_KEY", "")
os.environ.setdefault("ALPACA_SECRET_KEY", "")

from fastapi import HTTPException

import api
from engine.fingerprint import backtest_fingerprint

CURRENT = backtest_fingerprint()
STALE = "0000deadbeef"


def _row(row_id, fingerprint, total_return):
    """A saved backtest_results row as get_backtest_results returns it."""
    return {
        "id": row_id,
        "code_fingerprint": fingerprint,
        "total_return": total_return,
        "num_trades": 49,
        "created_at": "2026-08-01T00:00:00+00:00",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
    }


# Rows are ordered id DESC, matching get_backtest_results.
def _legacy_rows():
    """Pre-fingerprint rows: the real production shape, disagreeing on the answer."""
    return [
        _row(27, None, 0.0384),
        _row(26, None, 0.0384),
        _row(22, None, 0.29647782),
    ]


def test_stale_only_is_refused():
    """
    No run from the current code -> 422, not a silent results[0].

    This is the assertion the old code fails: it would have returned row 27 and
    reported +3.84% as if it were comparable.
    """
    rows = _legacy_rows()
    with pytest.raises(HTTPException) as exc:
        api._select_backtest(rows, None, "AAPL", "Momentum")

    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["error"] == "no_comparable_backtest"
    assert detail["current_code_fingerprint"] == CURRENT
    # The stale rows are named, so the caller can see what was rejected.
    assert [c["id"] for c in detail["rejected_candidates"]] == [27, 26, 22]


def test_picks_current_code_over_newer_stale_row():
    """A newer row from different code must lose to an older row from this code."""
    rows = [_row(30, STALE, 0.99)] + _legacy_rows() + [_row(20, CURRENT, 0.0384)]

    chosen, selection = api._select_backtest(rows, None, "AAPL", "Momentum")

    assert chosen["id"] == 20, "picked a row the current engine did not produce"
    assert rows[0]["id"] == 30, "fixture no longer exercises the results[0] trap"
    assert selection["selected_by"] == "newest_matching_code_fingerprint"
    assert selection["code_fingerprint_match"] is True
    assert selection["candidates_matching_code"] == 1
    assert [c["id"] for c in selection["candidates_rejected_stale_code"]] == [30, 27, 26, 22]


def test_picks_newest_among_matching():
    rows = [_row(31, CURRENT, 0.05), _row(20, CURRENT, 0.0384)]

    chosen, selection = api._select_backtest(rows, None, "AAPL", "Momentum")

    assert chosen["id"] == 31
    assert selection["candidates_matching_code"] == 2
    assert selection["candidates_rejected_stale_code"] == []


def test_explicit_id_wins_but_is_flagged_when_stale():
    """An explicit backtest_id is honoured - the caller said which one - but reported as stale."""
    rows = _legacy_rows()

    chosen, selection = api._select_backtest(rows, 22, "AAPL", "Momentum")

    assert chosen["id"] == 22
    assert selection["selected_by"] == "explicit_backtest_id"
    assert selection["code_fingerprint_match"] is False
    assert selection["backtest_code_fingerprint"] is None
    assert selection["current_code_fingerprint"] == CURRENT


def test_explicit_id_reported_as_matching_when_current():
    rows = [_row(20, CURRENT, 0.0384)]

    _, selection = api._select_backtest(rows, 20, "AAPL", "Momentum")

    assert selection["code_fingerprint_match"] is True


def test_unknown_explicit_id_is_422():
    with pytest.raises(HTTPException) as exc:
        api._select_backtest(_legacy_rows(), 999, "AAPL", "Momentum")
    assert exc.value.status_code == 422
    assert "999" in str(exc.value.detail)


def test_fingerprint_is_stable_and_tracks_file_contents():
    """A fingerprint that does not move when the engine changes would be worse than none."""
    import engine.fingerprint as fingerprint_module

    assert fingerprint_module.backtest_fingerprint() == CURRENT

    target = os.path.join(PROJECT_ROOT, "trading_constants.py")
    with open(target, "rb") as f:
        original = f.read()
    try:
        with open(target, "wb") as f:
            f.write(original + b"\n# fingerprint probe\n")
        assert fingerprint_module.backtest_fingerprint(refresh=True) != CURRENT
    finally:
        with open(target, "wb") as f:
            f.write(original)
        # Leave the process-level cache holding the true value for other tests.
        assert fingerprint_module.backtest_fingerprint(refresh=True) == CURRENT
