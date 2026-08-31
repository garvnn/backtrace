"""
Run a strategy over the longest history the vendor will give, and report the
sample size it was actually validated on.

Every saved backtest in the database uses 2020-01-01..2024-12-31 - about 1,258
trading days, one market regime and a bit. That is a thin sample to draw a
conclusion from: it contains one crash (2020), one melt-up, and one rate shock,
and no prolonged bear market. A strategy that survives it has not been tested
against 2000-2002 or 2008.

This runs the same engine over as much history as exists, prints the trading-day
count so the sample size can be stated honestly, and saves the result with a
code fingerprint so it is comparable to future runs.

Usage:
    python3 scripts/long_history_backtest.py
    python3 scripts/long_history_backtest.py --ticker SPY --start 1993-01-29
    python3 scripts/long_history_backtest.py --strategy "MA Crossover" --save

Note on start dates: AAPL trades from 1980-12-12, SPY from 1993-01-29. Asking
for earlier just returns less data, it does not fail.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "live"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--start", default="1980-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--strategy", default="Momentum")
    parser.add_argument("--save", action="store_true", help="Persist to backtest_results")
    args = parser.parse_args()

    # Run from the project root so data/cache resolves.
    os.chdir(ROOT)

    from analytics.metrics import calculate_metrics
    from data.loader import load_data
    from engine.backtest_engine import BacktestEngine
    from engine.fingerprint import backtest_fingerprint
    from strategies.ma_crossover import MACrossoverStrategy
    from strategies.momentum import MomentumStrategy
    from strategies.naming import MA_CROSSOVER, canonical

    name = canonical(args.strategy)
    strategy = (
        MACrossoverStrategy() if name == MA_CROSSOVER else MomentumStrategy()
    )

    print(f"Loading {args.ticker} {args.start} -> {args.end} ...")
    data = load_data(args.ticker, args.start, args.end)
    if data is None or data.empty:
        print("No data returned. Yahoo may be unreachable, or the symbol is wrong.")
        return 1

    engine = BacktestEngine()
    results = engine.run(data, strategy)
    metrics = calculate_metrics(results)
    benchmark = engine.run_buyhold(data)

    n_days = len(data)
    first, last = str(data.index[0])[:10], str(data.index[-1])[:10]
    years = n_days / 252.0

    print()
    print("=" * 68)
    print(f"{name} on {args.ticker}")
    print("=" * 68)
    print(f"Window          : {first} -> {last}")
    print(f"Trading days    : {n_days:,}  (~{years:.1f} years at 252/yr)")
    print(f"Calendar years  : {int(last[:4]) - int(first[:4])}")
    print()
    print(f"Total return    : {float(metrics['total_return']) * 100:+.2f}%")
    print(f"Sharpe ratio    : {float(metrics['sharpe_ratio']):.3f}   (zero risk-free rate)")
    print(f"Max drawdown    : {float(metrics['max_drawdown']) * 100:+.2f}%")
    print(f"Trades          : {int(metrics['num_trades'])}")
    print(f"Buy & hold      : {float(benchmark['total_return']) * 100:+.2f}%  (same sizing caps)")
    print()
    print(f"Code fingerprint: {backtest_fingerprint()}")
    print()
    print("For a resume claim, the defensible number is the trading-day count above,")
    print("not the calendar span - a strategy needing a 120-bar lookback has not been")
    print("tested on the first 120 rows of it.")

    if args.save:
        from database import Database

        db = Database(os.getenv("DB_PATH") or os.path.join(ROOT, "live", "trading.db"))
        row_id = db.save_backtest_results(
            name, args.ticker, first, last,
            float(metrics["total_return"]), float(metrics["sharpe_ratio"]),
            float(metrics["max_drawdown"]), int(metrics["num_trades"]),
            results["portfolio_values"],
            params={
                "strategy": name,
                "lookback_period": getattr(strategy, "lookback_period", None),
                "short_window": getattr(strategy, "short_window", None),
                "long_window": getattr(strategy, "long_window", None),
                "trading_days": n_days,
            },
            code_fingerprint=backtest_fingerprint(),
        )
        print(f"\nSaved as backtest_results id={row_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
