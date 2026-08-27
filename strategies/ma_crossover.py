"""
Moving Average Crossover: long while the fast MA is above the slow MA.

This is a trend-following rule. It lived in mean_reversion.py as
MeanReversionStrategy, which named it as the opposite of what it does - mean
reversion fades a move, this one follows it - while its own docstring, its
self.name, and the UI all already said "MA Crossover". The mismatch was
patched at four separate call sites instead of fixed once, and it had produced
a real frontend bug: App.js compared trade.strategy to 'MeanReversion' while
the executor wrote 'MA Crossover', so MA trades fell through to the momentum
branch and rendered their parameters as "Lookback - days".

The DB string stays "MA Crossover" (what live trades are keyed on) and
"MeanReversion" remains readable as a legacy alias for the backtest rows
written before this rename - see strategies/naming.py, which is now the only
place that mapping lives.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import Strategy


class MACrossoverStrategy(Strategy):
    def __init__(self, short_window=50, long_window=200):
        super().__init__(name="MA Crossover")
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, data):
        """
        Long (1) while the short MA is above the long MA, flat (0) otherwise.

        Long-only: there is no -1. Until the long window is warm the rolling
        means are NaN, the comparison is False, and the signal is flat - so the
        first long_window bars of any series never trade.
        """
        signals = pd.Series(0, index=data.index)

        short_ma = data['Close'].rolling(window=self.short_window).mean()
        long_ma = data['Close'].rolling(window=self.long_window).mean()

        # 1 = long, 0 = flat
        signals[short_ma > long_ma] = 1

        return signals


if __name__ == "__main__":
    from data.loader import load_data

    print("Testing MA crossover strategy...")
    data = load_data('AAPL', '2020-01-01', '2024-12-31')

    strategy = MACrossoverStrategy()
    signals = strategy.generate_signals(data)

    print(f"\nTotal signals: {len(signals)}")
    print(f"Long signals: {(signals == 1).sum()}")
    print(f"Flat signals: {(signals == 0).sum()}")
    print(f"\nFirst 10 signals:")
    print(signals.head(10))
