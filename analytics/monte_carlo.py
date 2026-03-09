"""
Monte Carlo simulation for strategy robustness testing.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def run_monte_carlo(portfolio_values, num_simulations=10000, initial_capital=100000):
    """
    Bootstrap returns to simulate possible outcomes.

    Args:
        portfolio_values: Series of portfolio values over time from backtest
        num_simulations: Number of simulation runs
        initial_capital: Starting portfolio value

    Returns:
        Dict with percentiles, probability_profit, histogram_data, mean, std.
        If there are too few returns to bootstrap, returns dict with
        error key for the API to handle.
    """
    if portfolio_values is None or len(portfolio_values) < 2:
        return {"error": "Equity curve has too few points for Monte Carlo (need at least 2)."}

    returns = portfolio_values.pct_change().dropna()
    num_days = len(returns)

    if num_days < 1:
        return {"error": "No daily returns available for Monte Carlo."}

    returns = np.asarray(returns)

    final_values = []
    for _ in range(num_simulations):
        sampled_returns = np.random.choice(returns, size=num_days, replace=True)
        cumulative_return = np.prod(1 + sampled_returns)
        final_value = initial_capital * cumulative_return
        final_values.append(final_value)

    final_values = np.array(final_values)

    percentiles = {
        5: float(np.percentile(final_values, 5)),
        50: float(np.percentile(final_values, 50)),
        95: float(np.percentile(final_values, 95)),
    }

    probability_profit = float(np.sum(final_values > initial_capital) / num_simulations)

    hist, bin_edges = np.histogram(final_values, bins=20)
    histogram_data = [
        {"bin": float((bin_edges[i] + bin_edges[i + 1]) / 2), "count": int(hist[i])}
        for i in range(len(hist))
    ]

    return {
        "percentiles": percentiles,
        "probability_profit": probability_profit,
        "histogram_data": histogram_data,
        "mean": float(np.mean(final_values)),
        "std": float(np.std(final_values)),
    }


if __name__ == "__main__":
    from data.loader import load_data
    from engine.backtest_engine import BacktestEngine
    from strategies.momentum import MomentumStrategy

    data = load_data("AAPL", "2020-01-01", "2024-12-31")
    if data is None or len(data) == 0:
        print("No data loaded. Exiting.")
        sys.exit(1)

    engine = BacktestEngine()
    strategy = MomentumStrategy()
    results = engine.run(data, strategy)

    mc_results = run_monte_carlo(results["portfolio_values"])

    if "error" in mc_results:
        print("Monte Carlo error:", mc_results["error"])
        sys.exit(1)

    print("\n" + "=" * 50)
    print("MONTE CARLO SIMULATION RESULTS")
    print("=" * 50)
    print("Number of simulations: 10,000")
    print(f"\n5th percentile:  ${mc_results['percentiles'][5]:,.2f}")
    print(f"50th percentile: ${mc_results['percentiles'][50]:,.2f}")
    print(f"95th percentile: ${mc_results['percentiles'][95]:,.2f}")
    print(f"\nProbability of profit: {mc_results['probability_profit']:.1%}")
    print(f"Mean outcome: ${mc_results['mean']:,.2f}")
    print(f"Std deviation: ${mc_results['std']:,.2f}")
    print("=" * 50)
