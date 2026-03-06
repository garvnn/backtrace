"""
Statistical Arbitrage (pairs trading) strategy.
Trades cointegrated pairs when the spread diverges (z-score) and mean-reverts.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from strategies.base import Strategy


class StatArbStrategy(Strategy):
    def __init__(self, ticker_a, ticker_b, lookback=60, entry_threshold=2.0, exit_threshold=0.5):
        super().__init__(name="Stat Arb")
        self.ticker_a = ticker_a
        self.ticker_b = ticker_b
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

    def generate_signals(self, data, data_b=None):
        """
        If data_b is None: single-asset not supported (raises).
        If data_b is provided: delegates to pair logic. Executor calls generate_signals(data_a, data_b).
        """
        if data_b is None:
            raise NotImplementedError("StatArbStrategy requires two price series; use generate_signals(data_a, data_b)")
        return self.generate_signals_pair(data, data_b)

    def generate_signals_pair(self, data_a, data_b):
        """
        Generate signals for both legs of the pair.

        Args:
            data_a: DataFrame with 'Close' for ticker A (same index as data_b)
            data_b: DataFrame with 'Close' for ticker B

        Returns:
            (signal_a, signal_b): tuple of two Series with 1 (long), -1 (short), 0 (flat)
            - z > entry_threshold  -> short spread -> signal_a=-1, signal_b=1
            - z < -entry_threshold -> long spread  -> signal_a=1, signal_b=-1
            - abs(z) < exit_threshold -> flat -> signal_a=0, signal_b=0
        """
        # Align by index
        common = data_a.index.intersection(data_b.index)
        pa = data_a.loc[common, "Close"].astype(float)
        pb = data_b.loc[common, "Close"].astype(float)
        pa = pa.dropna()
        pb = pb.reindex(pa.index).dropna()
        common = pa.index.intersection(pb.index)
        pa = pa.loc[common]
        pb = pb.loc[common]
        n = len(pa)
        if n < self.lookback:
            return (
                pd.Series(0, index=pa.index),
                pd.Series(0, index=pb.index),
            )

        signal_a = pd.Series(0, index=pa.index, dtype=int)
        signal_b = pd.Series(0, index=pb.index, dtype=int)
        last_sa, last_sb = 0, 0

        for i in range(self.lookback, n):
            window_a = pa.iloc[i - self.lookback : i].values
            window_b = pb.iloc[i - self.lookback : i].values
            # Hedge ratio: regress price_a on price_b
            beta = np.polyfit(window_b, window_a, 1)[0]
            # Spread in log space
            log_a = np.log(pa.iloc[i])
            log_b = np.log(pb.iloc[i])
            spread = log_a - beta * log_b
            spread_hist = np.log(window_a) - beta * np.log(window_b)
            mean_spread = np.mean(spread_hist)
            std_spread = np.std(spread_hist)
            if std_spread <= 0:
                signal_a.iloc[i] = last_sa
                signal_b.iloc[i] = last_sb
                continue
            z = (spread - mean_spread) / std_spread

            if z > self.entry_threshold:
                signal_a.iloc[i] = -1
                signal_b.iloc[i] = 1
                last_sa, last_sb = -1, 1
            elif z < -self.entry_threshold:
                signal_a.iloc[i] = 1
                signal_b.iloc[i] = -1
                last_sa, last_sb = 1, -1
            elif abs(z) < self.exit_threshold:
                signal_a.iloc[i] = 0
                signal_b.iloc[i] = 0
                last_sa, last_sb = 0, 0
            else:
                # Hold: between exit and entry threshold
                signal_a.iloc[i] = last_sa
                signal_b.iloc[i] = last_sb

        return signal_a, signal_b
