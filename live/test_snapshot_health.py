"""
Snapshot data-quality checks.

The fixtures here are the real production rows around 2026-07-07, the reading
that put a 61% max drawdown on a live curve whose actual return is +1.65%.
"""

import os
import sys

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from snapshot_health import (
    EMPTY_POSITIONS_VALUE_IS_CASH,
    ISOLATED_SPIKE,
    OK,
    UNRECONCILED,
    classify_series,
    clean_series,
    is_isolated_spike,
    looks_like_dropped_positions,
    reconcile_snapshot,
)

HELD = {"AAPL": 10, "MSFT": 8, "NVDA": 5, "GOOGL": 4, "AMZN": 6, "META": 3}


def _row(ts, value, cash, positions):
    return {"timestamp": ts, "portfolio_value": value, "cash": cash, "positions": positions}


def production_window():
    """The real snapshots around the defect, values as recorded."""
    return [
        _row("2026-07-01", 105_041.93, 43_102.17, HELD),
        _row("2026-07-02", 105_399.80, 33_130.13, {**HELD, "TSLA": 2}),
        _row("2026-07-03", 105_527.98, 33_130.12, {**HELD, "TSLA": 2}),
        _row("2026-07-06", 105_669.41, 43_135.35, HELD),
        _row("2026-07-07", 43_135.33, 43_135.33, {}),          # the defect
        _row("2026-07-08", 105_987.51, 3_491.40, HELD),
        _row("2026-07-09", 106_086.67, 3_081.42, HELD),
    ]


# --- write-time reconciliation ------------------------------------------------

def test_healthy_snapshot_reconciles():
    ok, reason, _ = reconcile_snapshot(105_669.41, 43_135.35, 62_534.06, 6)
    assert ok
    assert reason == OK


def test_value_omitting_positions_is_rejected():
    """The production defect, as it would appear at write time."""
    ok, reason, detail = reconcile_snapshot(43_135.33, 43_135.33, 62_534.06, 6)
    assert not ok
    assert reason == UNRECONCILED
    # The gap is the entire value of the holdings.
    assert abs(detail["gap"] + 62_534.06) < 1.0


def test_genuinely_flat_account_is_allowed_but_labelled():
    ok, reason, _ = reconcile_snapshot(43_135.33, 43_135.33, 0.0, 0)
    assert ok, "a flat account is a valid state"
    assert reason == EMPTY_POSITIONS_VALUE_IS_CASH


def test_small_marking_differences_are_tolerated():
    """Two endpoints called a moment apart will not agree to the penny."""
    ok, reason, _ = reconcile_snapshot(105_669.41, 43_135.35, 62_100.00, 6)
    assert ok and reason == OK


def test_gap_beyond_tolerance_is_rejected():
    ok, reason, _ = reconcile_snapshot(105_669.41, 43_135.35, 30_000.00, 6)
    assert not ok and reason == UNRECONCILED


def test_non_numeric_fields_do_not_raise():
    ok, reason, detail = reconcile_snapshot("not-a-number", 1.0, 2.0, 1)
    assert not ok and reason == UNRECONCILED and "error" in detail


def test_negative_cash_still_reconciles():
    """The account does go on margin - cash was -6,830.22 on 2026-07-10."""
    ok, reason, _ = reconcile_snapshot(106_119.51, -6_830.22, 112_949.73, 7)
    assert ok and reason == OK


# --- read-time classification -------------------------------------------------

def test_production_defect_is_identified():
    points = production_window()
    labels = classify_series(points)
    statuses = [l["status"] for l in labels]
    assert statuses.count(OK) == len(points) - 1
    bad = [l for l in labels if l["status"] != OK]
    assert len(bad) == 1
    assert bad[0]["timestamp"] == "2026-07-07"
    assert bad[0]["status"] == EMPTY_POSITIONS_VALUE_IS_CASH


def test_clean_series_drops_only_the_defect():
    kept, excluded = clean_series(production_window())
    assert len(kept) == 6
    assert len(excluded) == 1
    assert excluded[0]["timestamp"] == "2026-07-07"
    assert all(r["timestamp"] != "2026-07-07" for r in kept)


def test_removing_the_defect_removes_the_drawdown():
    """The point of the whole module."""
    def max_dd(rows):
        peak = float(rows[0]["portfolio_value"])
        worst = 0.0
        for r in rows:
            v = float(r["portfolio_value"])
            peak = max(peak, v)
            worst = min(worst, v / peak - 1.0)
        return worst

    points = production_window()
    assert max_dd(points) < -0.55, "fixture should reproduce the reported drawdown"
    kept, _ = clean_series(points)
    assert max_dd(kept) > -0.01, "with the bad row gone there is no drawdown to speak of"


def test_a_real_liquidation_is_not_flagged():
    """
    Selling out is a legitimate flat state. It moves cash - that is what
    distinguishes it from the defect, which leaves cash untouched.
    """
    rows = [
        _row("2026-07-06", 105_669.41, 43_135.35, HELD),
        _row("2026-07-07", 105_700.00, 105_700.00, {}),   # sold everything
        _row("2026-07-08", 105_710.00, 105_710.00, {}),
    ]
    labels = classify_series(rows)
    assert [l["status"] for l in labels] == [OK, OK, OK]


def test_a_real_sustained_decline_is_not_flagged():
    rows = [
        _row("2026-07-01", 100_000.0, 20_000.0, HELD),
        _row("2026-07-02", 88_000.0, 20_000.0, HELD),
        _row("2026-07-03", 74_000.0, 20_000.0, HELD),
        _row("2026-07-06", 61_000.0, 20_000.0, HELD),
        _row("2026-07-07", 58_000.0, 20_000.0, HELD),
    ]
    labels = classify_series(rows)
    assert all(l["status"] == OK for l in labels), "a real drawdown must survive"
    kept, excluded = clean_series(rows)
    assert len(kept) == 5 and excluded == []


def test_dropped_positions_needs_the_previous_row_to_have_held_something():
    rows = [
        _row("2026-07-06", 43_135.35, 43_135.35, {}),
        _row("2026-07-07", 43_135.33, 43_135.33, {}),
    ]
    assert not looks_like_dropped_positions(rows[1], rows[0])


def test_first_row_is_never_flagged_as_dropped():
    assert not looks_like_dropped_positions(_row("2026-07-07", 1.0, 1.0, {}), None)


def test_isolated_spike_detected_without_position_data():
    rows = [
        _row("2026-07-06", 100_000.0, 0.0, HELD),
        _row("2026-07-07", 40_000.0, 0.0, HELD),   # holds positions, so the
        _row("2026-07-08", 100_500.0, 0.0, HELD),  # cash heuristic won't fire
    ]
    assert is_isolated_spike(rows, 1)
    labels = classify_series(rows)
    assert labels[1]["status"] == ISOLATED_SPIKE


def test_spike_check_ignores_series_endpoints():
    rows = [_row("a", 100.0, 0.0, {}), _row("b", 101.0, 0.0, {})]
    assert not is_isolated_spike(rows, 0)
    assert not is_isolated_spike(rows, 1)


def test_empty_and_single_point_series_are_safe():
    assert clean_series([]) == ([], [])
    one = [_row("2026-07-07", 100.0, 100.0, {})]
    kept, excluded = clean_series(one)
    assert len(kept) == 1 and excluded == []
