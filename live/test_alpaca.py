"""
Test Alpaca API connection. Read-only (get_account() only, no orders) — manual smoke test.

Guarded behind __main__ for the same reason as test_order.py: this filename matches pytest's
test_*.py discovery pattern, and without the guard, `pytest live/` would make a real API call
on every collection.

Run explicitly: python live/test_alpaca.py
"""

import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient


def main():
    load_dotenv()

    api_key = os.getenv('ALPACA_API_KEY')
    secret_key = os.getenv('ALPACA_SECRET_KEY')

    # Create client (paper=True for paper trading)
    client = TradingClient(api_key, secret_key, paper=True)

    # Get account info
    account = client.get_account()

    print("=" * 50)
    print("ALPACA ACCOUNT INFO")
    print("=" * 50)
    print(f"Account Number: {account.account_number}")
    print(f"Buying Power: ${float(account.buying_power):,.2f}")
    print(f"Cash: ${float(account.cash):,.2f}")
    print(f"Portfolio Value: ${float(account.portfolio_value):,.2f}")
    print(f"Status: {account.status}")
    print("=" * 50)


if __name__ == "__main__":
    main()