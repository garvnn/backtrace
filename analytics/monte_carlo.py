"""
Monte Carlo simulation for strategy robustness testing.

Uses daily percentage returns from the equity curve and block-bootstrap resampling
to simulate realistic paths (avoids iid resampling which can produce unrealistic tails).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

# Block size for block bootstrap (consecutive days); preserves return autocorrelation
# and avoids unrealistic sequences (e.g. many copies of the best day).
DEFAULT_BLOCK_DAYS = 20


def run_monte_carlo(portfolio_values, num_simulations=10000, initial_capital=100000, block_days=DEFAULT_BLOCK_DAYS):
    """
    Block-bootstrap daily percentage returns to simulate possible outcomes.

    Uses daily % returns from portfolio_values (not cumulative values). Resamples
    blocks of consecutive daily returns so paths stay realistic.

    Args:
        portfolio_values: Series of portfolio values over time from backtest (daily).
        num_simulations: Number of simulation runs
        initial_capital: Starting portfolio value
        block_days: Block size for block bootstrap (default 20 trading days)

    Returns:
        Dict with percentiles, probability_profit, histogram_data, mean, std.
        If there are too few returns to bootstrap, returns dict with
        error key for the API to handle.
    """
    if portfolio_values is None or len(portfolio_values) < 2:
        return {"error": "Equity curve has too few points for Monte Carlo (need at least 2)."}

    # Daily percentage returns only (not cumulative values)
    daily_returns = portfolio_values.pct_change().dropna()
    daily_returns = np.asarray(daily_returns, dtype=float)
    num_returns = len(daily_returns)

    if num_returns < 1:
        return {"error": "No daily returns available for Monte Carlo."}

    # Sparse equity curves (e.g. only trade dates) would yield multi-period returns
    # and unrealistic variance; require enough points to be plausibly daily.
    if num_returns < 21:
        return {"error": "Too few return periods for Monte Carlo (need at least 21; use daily backtest data)."}

    block_days = min(max(1, block_days), num_returns)
    num_blocks = (num_returns + block_days - 1) // block_days

    # Build blocks of consecutive daily returns
    blocks = []
    for start in range(0, num_returns - block_days + 1):
        blocks.append(daily_returns[start : start + block_days])
    if not blocks:
        blocks = [daily_returns[:block_days].copy()]
    blocks = np.array(blocks)

    final_values = []
    rng = np.random.default_rng()
    for _ in range(num_simulations):
        # Block bootstrap: sample blocks with replacement, then concatenate to ~num_returns
        chosen = rng.integers(0, len(blocks), size=num_blocks)
        path = np.concatenate([blocks[i] for i in chosen])[:num_returns]
        # Compound daily returns: (1+r1)*(1+r2)*...
        cumulative_return = np.prod(1.0 + path)
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
