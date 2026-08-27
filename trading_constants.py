"""Shared trading parameters so backtest and live execution stay aligned."""

INITIAL_CAPITAL = 100_000
MAX_DOLLAR_PER_STOCK = 10_000
BUYING_POWER_FRACTION = 0.95
# Live pair sizing uses buying_power * this fraction (see live/executor.py).
PAIR_CAPITAL_FRACTION = 0.45
DEFAULT_COMMISSION = 0.001
