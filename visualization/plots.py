"""
Visualization functions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.pyplot as plt
import pandas as pd


def plot_comparison(results_dict, ticker, output_dir='results'):
    """
    Plot multiple strategies on same chart.
    
    Args:
        results_dict: Dict of {strategy_name: results}
        ticker: Stock ticker
        output_dir: Where to save
    """
    os.makedirs(output_dir, exist_ok=True)
    
    plt.figure(figsize=(14, 7))
    
    colors = ['#2E86AB', '#A23B72', '#F18F01', '#06A77D']
    
    for i, (name, results) in enumerate(results_dict.items()):
        portfolio_values = results['portfolio_values']
        plt.plot(portfolio_values.index, portfolio_values.values, 
                label=name, linewidth=2.5, color=colors[i % len(colors)])
    
    plt.title(f'Strategy Comparison - {ticker}', fontsize=18, fontweight='bold')
    plt.xlabel('Date', fontsize=13)
    plt.ylabel('Portfolio Value ($)', fontsize=13)
    plt.legend(fontsize=11, loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    filename = f"{output_dir}/comparison_{ticker}.png"
    plt.savefig(filename, dpi=150)
    print(f"Saved comparison chart: {filename}")
    plt.close()


if __name__ == "__main__":
    from data.loader import load_data
    from engine.backtest_engine import BacktestEngine
    from strategies.momentum import MomentumStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    
    print("Testing visualization...")
    
    data = load_data('AAPL', '2020-01-01', '2024-12-31')
    engine = BacktestEngine()
    
    # Run all strategies
    results = {
        'Buy & Hold': engine.run_buyhold(data),
        'MA Crossover': engine.run(data, MeanReversionStrategy()),
        'Momentum': engine.run(data, MomentumStrategy())
    }
    
    plot_comparison(results, 'AAPL')
    print("\nChart saved to results/ folder")