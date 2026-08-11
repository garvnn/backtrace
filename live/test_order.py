"""
Test placing orders. Places one real (paper) 1-share AAPL buy order — manual smoke test only.

Guarded behind __main__ on purpose: this filename matches pytest's test_*.py discovery pattern,
and without the guard, merely importing/collecting this file (e.g. `pytest live/`) executes the
submit_order() call immediately with no confirmation. That already happened twice for real.

Run explicitly: python live/test_order.py
"""

import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def main():
    load_dotenv()

    client = TradingClient(
        os.getenv('ALPACA_API_KEY'),
        os.getenv('ALPACA_SECRET_KEY'),
        paper=True
    )

    # Create a market order to buy 1 share of AAPL
    order_data = MarketOrderRequest(
        symbol="AAPL",
        qty=1,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY
    )

    # Submit the order
    order = client.submit_order(order_data)

    print("=" * 50)
    print("ORDER PLACED")
    print("=" * 50)
    print(f"Order ID: {order.id}")
    print(f"Symbol: {order.symbol}")
    print(f"Qty: {order.qty}")
    print(f"Side: {order.side}")
    print(f"Status: {order.status}")
    print("=" * 50)


if __name__ == "__main__":
    main()