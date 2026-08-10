"""
Fill status/price reconciliation: pull real order history from Alpaca and reconcile it into
the local `trades` table. Safe to re-run (idempotent) and safe against production data — this
script only ever reads from Alpaca and writes to the local DB; it never calls submit_order,
cancel_order, or anything else that touches real orders.

Why this exists: execute_signal() in executor.py logs whatever status Alpaca returns *at order
submission* (PENDING_NEW / ACCEPTED) and never checks again, so `trades.status` and `trades.price`
drift from reality — price is the last-close estimate used for sizing, not the actual fill price.
Meanwhile Alpaca has the real, confirmed fill status/price for every order. This script closes
that gap:
  1. For orders that already have a matching row (by order_id), UPDATE status/price if they've
     drifted from what Alpaca reports now (e.g. PENDING_NEW -> FILLED).
  2. For orders that exist on Alpaca but have no local row at all (e.g. because a batch scheduler
     run inserted the trade under a different process/DB, or logging was added after some orders
     were already placed), INSERT them so the local ledger reflects real trading history.

Run from live/ or project root with live/.env set:
    python live/sync_alpaca_fills.py
"""

import os
import sys

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(LIVE_DIR, ".env"))

from database import Database
DB_PATH = os.getenv("DB_PATH") or os.path.join(LIVE_DIR, "trading.db")

# Alpaca caps get_orders at 500 per page; paginate past that with `until` if needed.
ORDERS_PAGE_LIMIT = 500

# Strategy label used for orders found on Alpaca with no matching local trade row. Alpaca's
# Order object carries no strategy metadata (the scheduler picks a strategy per ticker per run
# via a backtest-based selector, see scheduler.py), so historical attribution isn't recoverable
# for these — they're tagged distinctly rather than silently mislabeled as a real strategy.
RECONCILED_STRATEGY_LABEL = "Unknown (reconciled)"


def _get_client():
    """Build a paper-trading TradingClient from live/.env keys, or None if keys are missing."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        return None
    from alpaca.trading.client import TradingClient
    return TradingClient(api_key, secret_key, paper=True)


def _normalize_status(status):
    """Normalize an Alpaca OrderStatus (enum or already-a-string) to a plain lowercase string,
    e.g. 'filled' rather than 'OrderStatus.FILLED' -- matches how the frontend's
    formatOrderStatus() in App.js already strips the 'OrderStatus.' prefix, so both existing and
    reconciled rows render consistently."""
    if status is None:
        return None
    value = getattr(status, "value", None)
    if value:
        return str(value).lower()
    return str(status).replace("OrderStatus.", "").lower()


def _normalize_side(side):
    """Normalize an Alpaca OrderSide (enum or string) to 'BUY'/'SELL', matching the local convention
    used by executor.py's execute_signal()."""
    value = getattr(side, "value", side)
    return str(value).upper()


def _order_timestamp(order):
    """Best available timestamp for a historical order: filled_at, else submitted_at, else created_at."""
    for attr in ("filled_at", "submitted_at", "created_at"):
        ts = getattr(order, attr, None)
        if ts is not None:
            return ts.isoformat()
    return None


def fetch_all_orders(client, page_limit=ORDERS_PAGE_LIMIT):
    """Fetch every order (any status) from Alpaca, paginating with `until` if there are more than
    page_limit. Orders are deduped by id in case pagination boundaries overlap."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    seen = {}
    until = None
    while True:
        request = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=page_limit,
            direction="desc",
            until=until,
        )
        batch = client.get_orders(request)
        if not batch:
            break
        new_in_batch = 0
        for order in batch:
            if str(order.id) not in seen:
                seen[str(order.id)] = order
                new_in_batch += 1
        if len(batch) < page_limit or new_in_batch == 0:
            break
        until = batch[-1].submitted_at
    return list(seen.values())


def sync_fills(db=None, client=None):
    """
    Reconcile the local `trades` table against Alpaca's real order history.
    Returns a dict: {orders_seen, updated, inserted, unchanged, total_trades} or
    {error: "..."} if Alpaca keys are missing / the API call fails.
    """
    if db is None:
        db = Database(DB_PATH)
    if client is None:
        client = _get_client()
        if client is None:
            return {"error": "Missing Alpaca keys (ALPACA_API_KEY/ALPACA_SECRET_KEY)"}

    try:
        orders = fetch_all_orders(client)
    except Exception as e:
        return {"error": f"Alpaca get_orders failed: {e}"}

    updated = 0
    inserted = 0
    unchanged = 0

    for order in orders:
        order_id = str(order.id)
        status = _normalize_status(order.status)
        filled_avg_price = getattr(order, "filled_avg_price", None)
        price = float(filled_avg_price) if filled_avg_price else None

        existing = db.get_trade_by_order_id(order_id)
        if existing is not None:
            _, existing_status, existing_price = existing
            existing_status_norm = _normalize_status(existing_status)
            status_changed = status is not None and status != existing_status_norm
            price_changed = price is not None and (
                existing_price is None or abs(float(existing_price) - price) > 1e-6
            )
            if status_changed or price_changed:
                new_price = price if price is not None else existing_price
                db.update_trade_fill(order_id, status, new_price)
                updated += 1
            else:
                unchanged += 1
            continue

        # No local row at all: insert so the ledger reflects real trading history.
        filled_qty = getattr(order, "filled_qty", None)
        qty_raw = filled_qty if filled_qty else getattr(order, "qty", None)
        try:
            qty = float(qty_raw) if qty_raw is not None else 0.0
        except (TypeError, ValueError):
            qty = 0.0

        db.log_trade(
            strategy=RECONCILED_STRATEGY_LABEL,
            ticker=order.symbol,
            side=_normalize_side(order.side),
            qty=qty,
            price=price,
            order_id=order_id,
            status=status,
            timestamp=_order_timestamp(order),
        )
        inserted += 1

    total_trades = len(db.get_all_trades())
    return {
        "orders_seen": len(orders),
        "updated": updated,
        "inserted": inserted,
        "unchanged": unchanged,
        "total_trades": total_trades,
    }


def main():
    print("=" * 60)
    print("ALPACA FILL SYNC (reconcile real order history into trades table)")
    print("=" * 60)
    result = sync_fills()
    if "error" in result:
        print(f"Skipped: {result['error']}")
        print("=" * 60)
        return 1

    print(f"Orders fetched from Alpaca:            {result['orders_seen']}")
    print(f"Existing trade rows updated (drifted):  {result['updated']}")
    print(f"Existing trade rows already in sync:     {result['unchanged']}")
    print(f"New trade rows inserted (missing locally): {result['inserted']}")
    print(f"Total trades in DB now:                  {result['total_trades']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
