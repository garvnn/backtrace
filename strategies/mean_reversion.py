"""
Moving Average Crossover Strategy.
"""


import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.base import Strategy

class MeanReversionStrategy(Strategy):
    def __init__(self, short_window=50, long_window=200):
        super().__init__(name="MA Crossover")
        self.short_window = short_window
        self.long_window = long_window
    
    def generate_signals(self, data):
        """
        Buy when short MA > long MA.
        Sell when short MA < long MA.
        """
        signals = pd.Series(0, index=data.index)
        
        short_ma = data['Close'].rolling(window=self.short_window).mean()
        long_ma = data['Close'].rolling(window=self.long_window).mean()
        
        # 1 = long, 0 = flat
        signals[short_ma > long_ma] = 1
        
        return signals


if __name__ == "__main__":
    from data.loader import load_data
    
    print("Testing mean reversion strategy...")
    data = load_data('AAPL', '2020-01-01', '2024-12-31')
    
    strategy = MeanReversionStrategy()
    signals = strategy.generate_signals(data)
    
    print(f"\nTotal signals: {len(signals)}")
    print(f"Long signals: {(signals == 1).sum()}")
    print(f"Flat signals: {(signals == 0).sum()}")
    print(f"\nFirst 10 signals:")
    print(signals.head(10))