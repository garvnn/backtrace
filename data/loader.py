"""
Data loading functionality.
Downloads stock data from Yahoo Finance and caches it locally.
"""

import os
import pandas as pd
import yfinance as yf

CACHE_DIR = 'data/cache'

def load_data(ticker, start_date, end_date):
    """
    Load stock data for a given ticker and date range.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL')
        start_date: Start date as string 'YYYY-MM-DD'
        end_date: End date as string 'YYYY-MM-DD'
        
    Returns:
        DataFrame with OHLCV data
    """
    # Create cache directory if it doesn't exist
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # Check if data is already cached
    cache_file = os.path.join(CACHE_DIR, f"{ticker}_{start_date}_{end_date}.csv")
    
    if os.path.exists(cache_file):
        print(f"Loading {ticker} from cache...")
        data = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        data = data.apply(pd.to_numeric, errors='coerce')
    else:
        print(f"Downloading {ticker} from Yahoo Finance...")
        data = yf.download(ticker, start=start_date, end=end_date, progress=False)
        data.to_csv(cache_file)
        print(f"Saved to cache: {cache_file}")
    
    return data


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