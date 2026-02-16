"""
Test Alpaca API connection.
"""

import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

# Load API keys
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