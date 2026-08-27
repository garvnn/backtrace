"""
Locate and explain the largest drawdown in the live equity curve.

The live curve reports a 61% peak-to-trough drawdown while the overall return
over the same window is +1.68%. Those two facts are hard to hold together: a
long/flat momentum strategy on ten large-cap names does not lose 61% and
recover inside 115 trading days without something visible happening. So either
the account really did move that way - which is a finding - or one snapshot is
wrong, which is a different finding. Both matter; guessing between them does
not.

This prints the peak and trough, the snapshots either side of the trough, and
whether the drop is a single-snapshot spike or a sustained decline. A one-row
dip that recovers on the very next snapshot is an artifact - a portfolio_value
read while an order was mid-fill, or a broker-side glitch - not a strategy
result. A decline over many rows is real.

Usage:
    python scripts/diagnose_drawdown.py --url https://your-api.up.railway.app
    python scripts/diagnose_drawdown.py --db live/trading.db

Reads /portfolio-history, which is not downsampled, rather than the equity
curves the dashboard endpoints return - a 400-point downsample of 1,144
snapshots can drop the very row being looked for.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import OrderedDict


def load_from_url(base_url: str) -> list[dict]:
    url = base_url.rstrip("/") + "/portfolio-history"
    print(f"Fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.load(resp)
    return payload.get("history", [])


def load_from_db(db_path: str) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, strategy, portfolio_value, cash, positions "
        "FROM portfolio_snapshots ORDER BY timestamp"
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "timestamp": r[0],
            "strategy": r[1],
            "portfolio_value": r[2],
            "cash": r[3],
            "positions": _safe_json(r[4]),
        }
        for r in rows
    ]


def _safe_json(raw):
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def to_daily(history: list[dict]) -> list[dict]:
    """
    Last snapshot of each calendar date.

    The scheduler used to snapshot once per ticker, so a single run wrote ten
    near-identical rows. Collapsing to one per date is what makes a "daily"
    return actually daily rather than intra-run.
    """
    by_date: "OrderedDict[str, dict]" = OrderedDict()
    for row in sorted(history, key=lambda r: r["timestamp"]):
        by_date[row["timestamp"][:10]] = row
    return list(by_date.values())


def max_drawdown(points: list[dict]) -> dict | None:
    """Largest peak-to-trough decline, with the rows that produced it."""
    if len(points) < 2:
        return None
    peak = points[0]
    worst = None
    for row in points:
        value = float(row["portfolio_value"])
        if value > float(peak["portfolio_value"]):
            peak = row
        peak_value = float(peak["portfolio_value"])
        if peak_value <= 0:
            continue
        dd = value / peak_value - 1.0
        if worst is None or dd < worst["drawdown"]:
            worst = {"drawdown": dd, "peak": peak, "trough": row}
    return worst


def describe(history: list[dict], label: str) -> None:
    points = to_daily(history)
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    print(f"Raw snapshots : {len(history)}")
    print(f"Distinct days : {len(points)}")
    if not points:
        print("No snapshots. Nothing to diagnose.")
        return
    print(f"Window        : {points[0]['timestamp'][:10]} -> {points[-1]['timestamp'][:10]}")
    first = float(points[0]["portfolio_value"])
    last = float(points[-1]["portfolio_value"])
    print(f"First / last  : {first:,.2f} -> {last:,.2f}")
    if first:
        print(f"Return        : {(last / first - 1.0) * 100:+.2f}%")

    worst = max_drawdown(points)
    if worst is None or worst["drawdown"] >= 0:
        print("\nNo drawdown found.")
        return

    peak, trough = worst["peak"], worst["trough"]
    print(f"\nMax drawdown  : {worst['drawdown'] * 100:+.2f}%")
    print(f"  peak   {peak['timestamp']}  {float(peak['portfolio_value']):>14,.2f}")
    print(f"  trough {trough['timestamp']}  {float(trough['portfolio_value']):>14,.2f}")

    # Context: is this one bad row, or a real decline?
    idx = next(i for i, r in enumerate(points) if r["timestamp"] == trough["timestamp"])
    lo, hi = max(0, idx - 4), min(len(points), idx + 5)
    print("\nSnapshots around the trough (>>> marks it):")
    print(f"  {'date':<12} {'value':>14} {'cash':>14}  {'chg':>8}  positions")
    prev = None
    for i in range(lo, hi):
        row = points[i]
        value = float(row["portfolio_value"])
        chg = f"{(value / prev - 1.0) * 100:+7.2f}%" if prev else "      -"
        n_pos = len(row.get("positions") or {})
        marker = ">>>" if i == idx else "   "
        print(
            f"{marker} {row['timestamp'][:10]:<12} {value:>14,.2f} "
            f"{float(row.get('cash') or 0):>14,.2f}  {chg:>8}  {n_pos} held"
        )
        prev = value

    # The verdict this script exists to deliver.
    print()
    recovered_next = (
        idx + 1 < len(points)
        and float(points[idx + 1]["portfolio_value"]) > float(trough["portfolio_value"]) * 1.5
    )
    if recovered_next:
        print(
            "VERDICT: single-snapshot spike - the next day is >50% higher. This is a bad\n"
            "         reading (portfolio_value sampled mid-fill, or a broker-side glitch),\n"
            "         not a strategy drawdown. Exclude it and re-measure."
        )
    else:
        print(
            "VERDICT: sustained decline across multiple snapshots - this looks like a real\n"
            "         move in the account, and belongs in the reported results."
        )

    # A cash-only account cannot be down 61%; if positions are empty at the
    # trough, the value is not describing what the account held.
    if not (trough.get("positions") or {}):
        print(
            "\nNOTE: the trough snapshot records zero positions. A flat account's value is\n"
            "      its cash, so a large drop with nothing held points at the snapshot rather\n"
            "      than the market."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Base URL of the deployed API")
    parser.add_argument("--db", help="Path to a SQLite trading.db instead")
    args = parser.parse_args()

    if not args.url and not args.db:
        parser.error("pass --url or --db")

    if args.url:
        describe(load_from_url(args.url), f"LIVE PORTFOLIO  {args.url}")
    if args.db:
        describe(load_from_db(args.db), f"LIVE PORTFOLIO  {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
