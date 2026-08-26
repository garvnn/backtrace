"""
Pre-validated stock pairs for stat arb.
"""

STOCK_PAIRS = {
    # Tech Giants
    'AAPL': ['MSFT', 'GOOGL', 'META'],
    'MSFT': ['AAPL', 'GOOGL', 'AMZN'],
    'GOOGL': ['AAPL', 'MSFT', 'META'],
    'META': ['GOOGL', 'SNAP', 'PINS'],
    # Financials
    'JPM': ['BAC', 'WFC', 'C'],
    'BAC': ['JPM', 'WFC', 'C'],
    'GS': ['MS', 'JPM', 'BAC'],
    # Consumer
    'KO': ['PEP'],
    'PEP': ['KO'],
    'MCD': ['YUM', 'SBUX'],
    'WMT': ['TGT', 'COST'],
    # Energy
    'XOM': ['CVX', 'COP'],
    'CVX': ['XOM', 'COP'],
}


def get_available_pairs(ticker):
    """Get valid pair options for a ticker."""
    return STOCK_PAIRS.get(ticker.upper() if ticker else '', [])


def is_valid_pair(ticker_a, ticker_b):
    """Check if pair is valid."""
    if not ticker_a or not ticker_b:
        return False
    a, b = ticker_a.upper().strip(), ticker_b.upper().strip()
    return b in STOCK_PAIRS.get(a, [])
