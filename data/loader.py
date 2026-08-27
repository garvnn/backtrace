"""
Data loading functionality.
Downloads stock data from Yahoo Finance and caches it locally.
"""

import os
import sys
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.symbols import to_yahoo

CACHE_DIR = 'data/cache'

def load_data(ticker, start_date, end_date):
    """
    Load stock data for a given ticker and date range.
    
    Args:
        ticker: Stock ticker in canonical (Alpaca) form, e.g. 'AAPL', 'BRK.B'.
                Translated to Yahoo's spelling for the download; the cache is
                keyed on the canonical form so it matches the database.
        start_date: Start date as string 'YYYY-MM-DD'
        end_date: End date as string 'YYYY-MM-DD'

    Returns:
        DataFrame with OHLCV data
    """
    # Create cache directory if it doesn't exist
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # Check if data is already cached
    # Suffix _adj: auto-adjusted OHLC (split/dividend) for parity with live Alpaca adjustment=all
    cache_file = os.path.join(CACHE_DIR, f"{ticker}_{start_date}_{end_date}_adj.csv")
    
    if os.path.exists(cache_file):
        print(f"Loading {ticker} from cache...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        df = df.apply(pd.to_numeric, errors='coerce')
    else:
        # Yahoo spells class shares BRK-B where Alpaca spells them BRK.B, and
        # returns an empty frame rather than raising on a symbol it does not
        # know - so the dot form failed silently.
        yahoo_ticker = to_yahoo(ticker)
        print(f"Downloading {ticker} from Yahoo Finance...")
        df = yf.download(yahoo_ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)

        # Flatten multi-index columns if they exist
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.to_csv(cache_file)
        print(f"Saved to cache: {cache_file}")
    
    return df


if __name__ == "__main__":
    # Test the loader
    print("Testing data loader...")
    test_data = load_data('AAPL', '2020-01-01', '2024-12-31')
    
    print(f"\nLoaded {len(test_data)} days of data")
    print("\nFirst 5 rows:")
    print(test_data.head())
    
    print("\nLast 5 rows:")
    print(test_data.tail())
    
    print("\nData columns:")
    print(test_data.columns.tolist())