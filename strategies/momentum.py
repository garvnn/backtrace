"""
Momentum Strategy.
Buy assets with positive past returns.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from strategies.base import Strategy


class MomentumStrategy(Strategy):
    def __init__(self, lookback_period=120):  # ~6 months
        super().__init__(name="Momentum")
        self.lookback_period = lookback_period
    
    def generate_signals(self, data):
        """
        Buy if past return is positive.
        Sell if past return is negative.
        """
        signals = pd.Series(0, index=data.index)
        
        # Calculate lookback returns
        returns = data['Close'].pct_change(periods=self.lookback_period)
        
        # 1 = long if positive momentum, 0 = flat otherwise
        signals[returns > 0] = 1
        
        return signals


if __name__ == "__main__":
    from data.loader import load_data
    from engine.backtest_engine import BacktestEngine
    from analytics.metrics import calculate_metrics
    
    print("Testing momentum strategy...")
    
    data = load_data('AAPL', '2020-01-01', '2024-12-31')
    
    strategy = MomentumStrategy()
    signals = strategy.generate_signals(data)
    
    print(f"\nTotal signals: {len(signals)}")
    print(f"Long signals: {(signals == 1).sum()}")
    print(f"Flat signals: {(signals == 0).sum()}")
    
    # Run backtest
    engine = BacktestEngine()
    results = engine.run(data, strategy)
    metrics = calculate_metrics(results)
    
    print("\n" + "="*50)
    print("MOMENTUM STRATEGY RESULTS")
    print("="*50)
    print(f"Total Return:    {metrics['total_return']:>8.2%}")
    print(f"Sharpe Ratio:    {metrics['sharpe_ratio']:>8.2f}")
    print(f"Max Drawdown:    {metrics['max_drawdown']:>8.2%}")
    print(f"Number of Trades: {metrics['num_trades']:>7}")
    print("="*50)