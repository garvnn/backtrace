"""
Alpaca connectivity check: confirms credentials work and reports account state.

Read-only — places no orders. Run from anywhere:
    python scripts/check_alpaca.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(PROJECT_ROOT, "live")

from dotenv import load_dotenv

load_dotenv(os.path.join(LIVE_DIR, ".env"))


def main():
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        print(
            "Missing Alpaca keys. Create live/.env with ALPACA_API_KEY and ALPACA_SECRET_KEY\n"
            "(paper keys: https://app.alpaca.markets/paper/dashboard/apis)"
        )
        return 1

    from alpaca.trading.client import TradingClient

    client = TradingClient(api_key, secret_key, paper=True)
    account = client.get_account()
    clock = client.get_clock()

    print("=" * 52)
    print("ALPACA PAPER ACCOUNT")
    print("=" * 52)
    print(f"Account number:   {account.account_number}")
    print(f"Status:           {account.status}")
    print(f"Portfolio value:  ${float(account.portfolio_value):,.2f}")
    print(f"Equity:           ${float(account.equity):,.2f}")
    print(f"Cash:             ${float(account.cash):,.2f}")
    print(f"Buying power:     ${float(account.buying_power):,.2f}")
    # Ratio of buying_power to equity is the account's effective leverage. Live sizing
    # must key off cash/equity, not buying_power, or it will run at this multiple.
    equity = float(account.equity)
    if equity:
        print(f"Leverage (BP/eq): {float(account.buying_power) / equity:.2f}x")
    print(f"Shorting enabled: {account.shorting_enabled}")
    print("-" * 52)
    print(f"Market open now:  {clock.is_open}")
    print(f"Next open:        {clock.next_open}")
    print(f"Next close:       {clock.next_close}")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())
