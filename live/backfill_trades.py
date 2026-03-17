"""
One-off script: copy trades from project-root trading.db into live/trading.db.

Use if the executor previously wrote to ./trading.db (before the path fix).
Run once manually from project root: python live/backfill_trades.py
"""

import os
import sqlite3

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
LIVE_DB = os.getenv("DB_PATH") or os.path.join(LIVE_DIR, "trading.db")
ROOT_DB = os.path.join(PROJECT_ROOT, "trading.db")


def main():
    if not os.path.isfile(ROOT_DB):
        print(f"No {ROOT_DB} found. Nothing to backfill.")
        return
    conn = sqlite3.connect(LIVE_DB)
    conn.execute("ATTACH DATABASE ? AS old_db", (ROOT_DB,))
    cursor = conn.cursor()
    # Get existing order_ids in live DB to avoid duplicates
    cursor.execute("SELECT order_id FROM trades WHERE order_id IS NOT NULL")
    existing = {row[0] for row in cursor.fetchall()}
    cursor.execute(
        "SELECT timestamp, strategy, ticker, side, qty, price, order_id, status, params FROM old_db.trades"
    )
    rows = cursor.fetchall()
    inserted = 0
    for row in rows:
        order_id = row[6]
        if order_id and order_id in existing:
            continue
        cursor.execute(
            """INSERT INTO trades (timestamp, strategy, ticker, side, qty, price, order_id, status, params)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        inserted += 1
        if order_id:
            existing.add(order_id)
    conn.commit()
    conn.close()
    print(f"Backfilled {inserted} trades from {ROOT_DB} into {LIVE_DB}.")


if __name__ == "__main__":
    main()
