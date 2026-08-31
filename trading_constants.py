"""Shared trading parameters so backtest and live execution stay aligned."""

INITIAL_CAPITAL = 100_000
MAX_DOLLAR_PER_STOCK = 10_000

# Share of available capital that may be deployed, holding the rest back.
#
# Named BUYING_POWER_FRACTION until it caused the bug it was named after: the
# executor read it as licence to size against account.buying_power, which on a
# margin paper account is roughly 2x equity, while the backtest applied the
# same fraction to cash. Production went to -$6,830.22 cash on 2026-07-10.
# Capital is cash or equity. buying_power is a margin allowance, not money.
CAPITAL_FRACTION = 0.95

# Per-leg share of capital for a two-legged spread, applied after
# CAPITAL_FRACTION. See trading/sizing.py.
PAIR_CAPITAL_FRACTION = 0.45
DEFAULT_COMMISSION = 0.001

# Alpaca market-data feed. The free plan serves IEX, which is a few percent of
# consolidated volume, so Alpaca daily closes differ from Yahoo's consolidated
# closes for reasons that have nothing to do with any strategy. That gap is one
# of the things analytics/divergence.py sets out to measure, which makes it
# worth stating outright rather than inheriting from a server default: an
# unstated feed means the vendor divergence could be a real finding or a
# free-tier artifact and nothing in the code says which.
#
# Set ALPACA_DATA_FEED=sip if the account has a paid market-data subscription.
ALPACA_DATA_FEED = "iex"
