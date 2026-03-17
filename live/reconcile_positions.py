"""
Position reconciliation: compare Alpaca positions with database (latest portfolio snapshot).
Flags mismatches and prints a report. Run from live/ or project root with live/.env set.
"""

import os
import sys
import json

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(LIVE_DIR, ".env"))

from database import Database
DB_PATH = os.getenv("DB_PATH") or os.path.join(LIVE_DIR, "trading.db")


def fetch_alpaca_positions():
    """Return dict symbol -> quantity from Alpaca, or None if unavailable."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        return None
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=True)
        positions = client.get_all_positions()
        return {pos.symbol: float(pos.qty) for pos in positions if float(pos.qty) != 0}
    except Exception as e:
        print(f"Alpaca fetch error: {e}")
        return None


def fetch_db_positions():
    """Return dict symbol -> quantity from latest portfolio_snapshot (any strategy)."""
    db = Database(DB_PATH)
    history = db.get_portfolio_history()
    if not history:
        return {}
    latest = history[-1]
    positions_raw = latest[5]
    if not positions_raw:
        return {}
    try:
        return json.loads(positions_raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def reconcile():
    """Compare Alpaca vs DB positions and return (alpaca_pos, db_pos, mismatches, report_lines)."""
    alpaca_pos = fetch_alpaca_positions()
    db_pos = fetch_db_positions()
    if alpaca_pos is None:
        return None, db_pos, [], ["Alpaca positions unavailable (missing keys or API error)."]
    all_symbols = set(alpaca_pos.keys()) | set(db_pos.keys())
    mismatches = []
    report = []
    report.append("Symbol       | Alpaca Qty | DB Qty     | Match")
    report.append("-" * 55)
    for sym in sorted(all_symbols):
        a_q = alpaca_pos.get(sym, 0)
        d_q = db_pos.get(sym, 0)
        try:
            a_f, d_f = float(a_q), float(d_q)
        except (TypeError, ValueError):
            a_f, d_f = 0.0, 0.0
        match = abs(a_f - d_f) < 0.001
        if not match:
            mismatches.append((sym, a_f, d_f))
        report.append(f"{sym:<12} | {a_f:>10.2f} | {d_f:>10.2f} | {'OK' if match else 'MISMATCH'}")
    return alpaca_pos, db_pos, mismatches, report


def main():
    print("=" * 60)
    print("POSITION RECONCILIATION (Alpaca vs Database)")
    print("=" * 60)
    alpaca_pos, db_pos, mismatches, report_lines = reconcile()
    for line in report_lines:
        print(line)
    print("-" * 60)
    if alpaca_pos is None:
        print("Skipped Alpaca comparison (no API keys or error).")
        print("DB-only snapshot positions:", db_pos)
    else:
        print(f"Alpaca positions: {len(alpaca_pos)} symbols")
        print(f"DB snapshot positions: {len(db_pos)} symbols")
        if mismatches:
            print(f"MISMATCHES: {len(mismatches)}")
            for sym, a_q, d_q in mismatches:
                print(f"  {sym}: Alpaca={a_q}, DB={d_q}")
        else:
            print("All positions match.")
    print("=" * 60)
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
