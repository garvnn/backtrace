"""
Pair selection tool for statistical arbitrage.
Finds cointegrated stock pairs from a fixed universe using yfinance and statsmodels.
Run from project root: python live/pairs_finder.py
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.stattools import coint

from data.symbols import to_alpaca, to_yahoo

# Allow running from project root or live/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Fixed universe: tech + beverage (liquid names likely to have cointegrated pairs)
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "AMD", "INTC",
    "CRM", "ADBE", "ORCL", "CSCO", "IBM", "QCOM", "AVGO", "TXN",
    "AMAT", "LRCX", "KO", "PEP",
]

# Default lookback for discovery (days)
START_DAYS_AGO = 365 * 3  # ~3 years
END_DAYS_AGO = 0
PVALUE_THRESHOLD = 0.05
TOP_N = 5


def download_prices(symbols, start_date, end_date):
    """Download daily close prices for all symbols; return DataFrame with aligned index."""
    # Yahoo spells class shares with a hyphen where Alpaca uses a dot. The
    # current universe has none, but this file now feeds pairs_config, so a
    # symbol added later must not silently return an empty frame.
    df = yf.download(
        [to_yahoo(s) for s in symbols],
        start=start_date,
        end=end_date,
        progress=False,
        group_by="ticker",
        auto_adjust=True,
        threads=False,
    )
    if df.empty:
        return pd.DataFrame()
    if not isinstance(df.columns, pd.MultiIndex):
        # Single symbol: columns are Open, High, Low, Close, Volume
        close_col = "Close" if "Close" in df.columns else "Adj Close"
        out = pd.DataFrame({symbols[0]: df[close_col]})
        return out
    # Multi-index: (Ticker, OHLC) -> extract Close per symbol.
    #
    # Columns come back spelled the way Yahoo was asked, so look up by the
    # Yahoo form and key the result by the canonical (Alpaca) one - callers,
    # and pairs_output.json, speak canonical.
    closes = {}
    for sym in symbols:
        yahoo_sym = to_yahoo(sym)
        try:
            if (yahoo_sym, "Close") in df.columns:
                closes[sym] = df[(yahoo_sym, "Close")].copy()
            elif (yahoo_sym, "Adj Close") in df.columns:
                closes[sym] = df[(yahoo_sym, "Adj Close")].copy()
            else:
                # level 0 = ticker, level 1 = OHLC
                sub = df[yahoo_sym] if yahoo_sym in df.columns.get_level_values(0) else None
                if sub is not None and "Close" in sub.columns:
                    closes[sym] = sub["Close"].copy()
        except (KeyError, TypeError):
            continue
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes).dropna(how="all")


def find_cointegrated_pairs(
    symbols=None,
    start_date=None,
    end_date=None,
    pvalue_threshold=PVALUE_THRESHOLD,
    top_n=TOP_N,
):
    """
    Test all pairs for cointegration; return top pairs with spread stats.
    Returns list of dicts: ticker_a, ticker_b, pvalue, beta, spread_mean, spread_std.
    """
    symbols = symbols or UNIVERSE
    if end_date is None:
        end_date = pd.Timestamp.now().normalize()
    if start_date is None:
        start_date = end_date - pd.Timedelta(days=START_DAYS_AGO)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"Downloading data for {len(symbols)} symbols from {start_str} to {end_str}...")
    prices = download_prices(symbols, start_str, end_str)
    if prices.empty or len(prices) < 100:
        print("Not enough data.")
        return []

    # Align: drop rows with any NaN so coint gets same-length series
    prices = prices.dropna()
    if len(prices) < 100:
        print("Not enough aligned data.")
        return []

    results = []
    n = len(symbols)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = symbols[i], symbols[j]
            if a not in prices.columns or b not in prices.columns:
                continue
            pa = prices[a].astype(float)
            pb = prices[b].astype(float)
            common = pa.index.intersection(pb.index)
            pa = pa.reindex(common).dropna()
            pb = pb.reindex(common).dropna()
            common = pa.index.intersection(pb.index)
            pa = pa.loc[common]
            pb = pb.loc[common]
            if len(pa) < 100:
                continue
            try:
                score, pvalue, _ = coint(pa, pb)
            except Exception:
                continue
            if pvalue >= pvalue_threshold:
                continue
            # Hedge ratio (beta): regress price_a on price_b
            beta = np.polyfit(pb.values, pa.values, 1)[0]
            # Spread in log space (as in strategy)
            log_a = np.log(pa.values)
            log_b = np.log(pb.values)
            spread = log_a - beta * log_b
            spread_mean = float(np.mean(spread))
            spread_std = float(np.std(spread))
            if spread_std <= 0:
                continue
            results.append({
                "ticker_a": a,
                "ticker_b": b,
                "pvalue": float(pvalue),
                "beta": float(beta),
                "spread_mean": spread_mean,
                "spread_std": spread_std,
            })

    # Sort by pvalue (lower = stronger cointegration)
    results.sort(key=lambda x: x["pvalue"])
    return results[:top_n]


def main():
    pairs = find_cointegrated_pairs(pvalue_threshold=PVALUE_THRESHOLD, top_n=TOP_N)
    if not pairs:
        print("No cointegrated pairs found (pvalue < 0.05). Try a different universe or date range.")
        return

    print("\n" + "=" * 70)
    print("Top cointegrated pairs (pvalue < 0.05)")
    print("=" * 70)
    for i, p in enumerate(pairs, 1):
        print(f"\n{i}. {p['ticker_a']} / {p['ticker_b']}")
        print(f"   pvalue:      {p['pvalue']:.6f}")
        print(f"   beta:        {p['beta']:.4f}")
        print(f"   spread_mean: {p['spread_mean']:.6f}")
        print(f"   spread_std:  {p['spread_std']:.6f}")
        print(f"   pair_name:   {p['ticker_a']}-{p['ticker_b']}")

    # Optionally save for executor/API
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pairs_output.json")
    with open(out_path, "w") as f:
        json.dump(pairs, f, indent=2)
    print(f"\nSaved top {len(pairs)} pairs to {out_path}")


if __name__ == "__main__":
    main()
