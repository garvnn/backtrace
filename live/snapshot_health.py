"""
Whether an account snapshot describes a state the account can actually be in.

Diagnosed from production. On 2026-07-07 at 20:30:10 UTC - 16:30 ET, the exact
minute the scheduler fires - Alpaca returned:

    portfolio_value  43,135.33
    cash             43,135.33
    positions        {}

The day before held six positions at 105,669.41 with the same 43,135.35 of
cash; the day after held six again at 105,987.51. The account did not lose
59% and regain it overnight. It was sampled mid-mark at the close, before
positions were marked, and both get_account() and get_all_positions() briefly
agreed on a state that omitted every holding.

BackTrace wrote that reading down as a real equity point, and one such row
produced a 61% peak-to-trough drawdown in every metric computed off the live
curve - against an overall return of +1.65%. The drawdown was not a strategy
result; it was a data-quality defect being reported as one.

Two checks, and the reason they are separate:

  reconcile_snapshot() runs at write time, where position market values are
  available from the broker, and asks the accounting question directly: does
  portfolio_value equal cash plus the marked value of what is held? This is
  the real test, and it catches the bad row before it is ever persisted.

  classify_series() runs at read time over stored rows, which record only
  {symbol: qty} and so cannot be re-marked. It catches the same defect by its
  shape - a value collapsing to exactly cash with nothing held, between rows
  that held positions - so the 1,154 snapshots already in production can be
  excluded from metrics without being deleted.

Nothing here deletes or rewrites a snapshot. A bad reading is evidence about
the data feed and stays in the table; it is excluded from equity metrics and
labelled, which is the same posture execution_logs takes toward no-trade
decisions.
"""

from __future__ import annotations

#: portfolio_value vs cash + positions must agree within this fraction of
#: portfolio_value. Loose enough for the marking differences a broker will
#: legitimately have between endpoints called a moment apart, tight enough
#: that an omitted position cannot hide inside it.
RECONCILE_TOLERANCE = 0.02

#: A snapshot whose value is within this fraction of its own cash is holding
#: nothing of consequence, whatever its positions field claims.
VALUE_IS_CASH_TOLERANCE = 0.001

#: Seconds to wait before re-reading an account that did not reconcile. The
#: defect is a mid-mark reading at the close, so a moment's delay resolves it.
#: Lives here rather than in trading_constants.py because that file is
#: fingerprinted for backtest comparability, and a snapshot retry has no
#: bearing on what a backtest returns.
SNAPSHOT_RETRY_DELAY_SECONDS = 3.0

#: How far a single row must fall and immediately recover to be called a
#: spike rather than a move. 0.25 = lost a quarter of its value and got it back.
SPIKE_THRESHOLD = 0.25

OK = "ok"
UNRECONCILED = "unreconciled_value_vs_positions"
EMPTY_POSITIONS_VALUE_IS_CASH = "positions_empty_value_equals_cash"
ISOLATED_SPIKE = "isolated_spike"


def reconcile_snapshot(portfolio_value, cash, positions_market_value, held_count):
    """
    Write-time check: does portfolio_value account for what is held?

    positions_market_value is the summed market value of open positions, and
    held_count how many there are - both from the broker, at the moment of the
    snapshot. Returns (ok, reason, detail).

    An account that is genuinely flat is fine: zero positions and value equal
    to cash is the correct description of a flat account. What is rejected is
    value equal to cash while positions exist, or a value that does not add up.
    """
    try:
        value = float(portfolio_value)
        cash_v = float(cash)
        pos_v = float(positions_market_value or 0.0)
    except (TypeError, ValueError) as exc:
        return False, UNRECONCILED, {"error": f"non-numeric snapshot field: {exc}"}

    expected = cash_v + pos_v
    gap = value - expected
    tolerance = max(abs(value), abs(expected), 1.0) * RECONCILE_TOLERANCE

    detail = {
        "portfolio_value": value,
        "cash": cash_v,
        "positions_market_value": pos_v,
        "expected_value": expected,
        "gap": gap,
        "tolerance": tolerance,
        "held_count": held_count,
    }

    if abs(gap) > tolerance:
        return False, UNRECONCILED, detail

    # The production failure: value collapsed to cash while the account held
    # something. Reconciliation alone can miss this when the position fetch
    # returns empty in the same instant, so check it explicitly.
    if held_count == 0 and abs(value - cash_v) <= abs(value) * VALUE_IS_CASH_TOLERANCE:
        # Genuinely flat, or a mid-mark reading that dropped the positions.
        # Indistinguishable from this call alone - the caller compares against
        # the previous snapshot to decide.
        return True, EMPTY_POSITIONS_VALUE_IS_CASH, detail

    return True, OK, detail


def looks_like_dropped_positions(row, previous):
    """
    Does this row look like the mid-mark defect, judged against the one before it?

    True when the row holds nothing and its value is its cash, while the
    previous row held positions and was worth materially more. A real
    liquidation moves cash; this defect leaves cash untouched, which is what
    makes it identifiable after the fact.
    """
    if previous is None:
        return False
    if (row.get("positions") or {}):
        return False

    try:
        value = float(row["portfolio_value"])
        cash = float(row.get("cash") or 0.0)
        prev_value = float(previous["portfolio_value"])
        prev_cash = float(previous.get("cash") or 0.0)
    except (TypeError, ValueError, KeyError):
        return False

    if not (previous.get("positions") or {}):
        return False
    if abs(value - cash) > abs(value) * VALUE_IS_CASH_TOLERANCE:
        return False
    if prev_value <= 0 or value >= prev_value * (1 - SPIKE_THRESHOLD):
        return False
    # Cash essentially unchanged: nothing was sold to produce this.
    return abs(cash - prev_cash) <= max(abs(prev_cash), 1.0) * 0.01


def is_isolated_spike(points, i):
    """
    Does row i fall sharply and recover on the very next row?

    A drawdown that reverses completely in one step is not a drawdown. This is
    the vendor-agnostic check, used for rows the positions heuristic does not
    catch.
    """
    if i <= 0 or i + 1 >= len(points):
        return False
    try:
        prev_v = float(points[i - 1]["portfolio_value"])
        curr_v = float(points[i]["portfolio_value"])
        next_v = float(points[i + 1]["portfolio_value"])
    except (TypeError, ValueError, KeyError):
        return False
    if prev_v <= 0 or curr_v <= 0:
        return False
    fell = curr_v < prev_v * (1 - SPIKE_THRESHOLD)
    recovered = next_v > prev_v * (1 - SPIKE_THRESHOLD / 2)
    return fell and recovered


def classify_series(points):
    """
    Label stored snapshots, oldest first.

    Returns a list the same length as points, each entry a dict with "status"
    (OK or a reason) and "index". Callers exclude non-OK rows from equity
    metrics; nothing is mutated or removed.
    """
    out = []
    for i, row in enumerate(points):
        previous = points[i - 1] if i > 0 else None
        if looks_like_dropped_positions(row, previous):
            status = EMPTY_POSITIONS_VALUE_IS_CASH
        elif is_isolated_spike(points, i):
            status = ISOLATED_SPIKE
        else:
            status = OK
        out.append({"index": i, "status": status, "timestamp": row.get("timestamp")})
    return out


def clean_series(points):
    """
    (kept_points, excluded) with data-quality defects removed.

    This is what equity metrics should measure. Excluded rows are returned
    alongside so a caller can report how many there were rather than quietly
    dropping them.
    """
    labels = classify_series(points)
    kept, excluded = [], []
    for row, label in zip(points, labels):
        if label["status"] == OK:
            kept.append(row)
        else:
            excluded.append({**label, "portfolio_value": row.get("portfolio_value")})
    return kept, excluded
