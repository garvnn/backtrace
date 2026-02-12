"""
Performance metrics calculations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def calculate_metrics(results):
    """
    Calculate performance metrics from backtest results.
    
    Args:
        results: Dict with 'portfolio_values', 'total_return', 'trades'
        
    Returns:
        Dict with all metrics
    """
    portfolio_values = results['portfolio_values']
    
    # Daily returns
    daily_returns = portfolio_values.pct_change().dropna()
    
    # Sharpe Ratio (annualized, assuming 252 trading days)
    if len(daily_returns) > 0 and daily_returns.std() != 0:
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0
    
    # Max Drawdown
    cumulative = portfolio_values
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min()
    
    # Win rate (not applicable for buy-hold, placeholder)
    win_rate = 0.0  # Will implement properly when we track individual trades
    
    return {
        'total_return': results['total_return'],
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'win_rate': win_rate,
        'num_trades': results['trades']
    }


if __name__ == "__main__":
    from data.loader import load_data
    from engine.backtest_engine import BacktestEngine
    from strategies.mean_reversion import MeanReversionStrategy
    
    print("Testing metrics...")
    
    data = load_data('AAPL', '2020-01-01', '2024-12-31')
    engine = BacktestEngine()
    strategy = MeanReversionStrategy()
    
    results = engine.run(data, strategy)
    metrics = calculate_metrics(results)
    
    print("\n" + "="*50)
    print("PERFORMANCE METRICS")
    print("="*50)
    print(f"Total Return:    {metrics['total_return']:>8.2%}")
    print(f"Sharpe Ratio:    {metrics['sharpe_ratio']:>8.2f}")
    print(f"Max Drawdown:    {metrics['max_drawdown']:>8.2%}")
    print(f"Number of Trades: {metrics['num_trades']:>7}")
    print("="*50)