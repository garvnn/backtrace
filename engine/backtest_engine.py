"""
Core backtesting engine.
Executes trades and tracks portfolio value over time.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np


class BacktestEngine:
    def __init__(self, initial_capital=100000, commission=0.001):
        """
        Args:
            initial_capital: Starting cash
            commission: Transaction cost (0.001 = 0.1%)
        """
        self.initial_capital = initial_capital
        self.commission = commission
    
    def run_buyhold(self, data):
        """
        Calculate buy-and-hold returns.
        
        Args:
            data: DataFrame with 'Close' prices
            
        Returns:
            Dict with portfolio values and metrics
        """
        # Calculate daily returns
        returns = data['Close'].pct_change()
        
        # Calculate cumulative portfolio value
        portfolio_values = self.initial_capital * (1 + returns).cumprod()
        portfolio_values.iloc[0] = self.initial_capital
        
        total_return = (float(portfolio_values.iloc[-1]) / self.initial_capital) - 1
        
        return {
            'portfolio_values': portfolio_values,
            'total_return': total_return,
            'trades': 1  # Just the initial buy
        }


if __name__ == "__main__":
    # Test the engine
    from data.loader import load_data
    
    print("Testing backtest engine...")
    data = load_data('AAPL', '2020-01-01', '2024-12-31')
    
    engine = BacktestEngine(initial_capital=100000)
    results = engine.run_buyhold(data)
    
    print(f"\nInitial Capital: ${engine.initial_capital:,.2f}")
    print(f"Final Value: ${float(results['portfolio_values'].iloc[-1]):,.2f}")
    print(f"Total Return: {results['total_return']:.2%}")