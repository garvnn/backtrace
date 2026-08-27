"""
Ticker symbol translation between market-data vendors.

BackTrace deliberately runs two vendors: Yahoo for backtests, Alpaca for live
execution. That is what makes estimate_data_source_impact meaningful - the
backtest/live gap can be decomposed into a vendor component only if the two
sides actually come from different vendors. The cost of that choice is that the
two disagree on how to spell a symbol, and nothing was paying it.

Class shares are the case that bites. Berkshire Hathaway class B is:

    BRK.B   Alpaca (and most US brokers)
    BRK-B   Yahoo Finance

live/scheduler.py trades the universe in Alpaca's spelling, so live trades and
execution logs are keyed "BRK.B". Every backtest, divergence report and
/daily-bars call for that ticker went to yfinance with the dot intact, which is
not a symbol Yahoo knows - it returns an empty frame rather than raising, so
the failure surfaced as "no data for this ticker", not as a bug. One name in
the ten-ticker universe silently had no backtest to compare against.

Canonical form inside BackTrace is Alpaca's, because that is what the broker
fills, what the database is keyed on, and what already exists in production
rows. Translation happens at the vendor boundary - to_yahoo() immediately
before a yfinance call - so nothing else has to know the difference.
"""

from __future__ import annotations

# Symbols where the mapping is not the general rule below. Empty today; it
# exists so that the next irregular symbol is a one-line data change rather
# than a second special case bolted into the logic.
_YAHOO_OVERRIDES: dict[str, str] = {}

_ALPACA_OVERRIDES: dict[str, str] = {v: k for k, v in _YAHOO_OVERRIDES.items()}


def to_yahoo(symbol: str) -> str:
    """
    Canonical (Alpaca) symbol -> Yahoo Finance symbol.

    Yahoo separates a share class with a hyphen where Alpaca uses a dot:
    BRK.B -> BRK-B, BF.B -> BF-B. Symbols without a class suffix are unchanged.
    """
    if not symbol:
        return symbol
    sym = symbol.strip().upper()
    if sym in _YAHOO_OVERRIDES:
        return _YAHOO_OVERRIDES[sym]
    return sym.replace(".", "-")


def to_alpaca(symbol: str) -> str:
    """
    Yahoo Finance symbol -> canonical (Alpaca) symbol.

    The inverse of to_yahoo for US equities. Note this is not safe to apply
    blindly to every Yahoo symbol: Yahoo also uses a hyphen in some non-equity
    identifiers, where it does not mean a share class. Use it on tickers that
    came from this project's own universe, not on arbitrary input.
    """
    if not symbol:
        return symbol
    sym = symbol.strip().upper()
    if sym in _ALPACA_OVERRIDES:
        return _ALPACA_OVERRIDES[sym]
    return sym.replace("-", ".")


if __name__ == "__main__":
    for s in ("AAPL", "BRK.B", "BF.B", "brk.b"):
        y = to_yahoo(s)
        print(f"{s:8s} -> yahoo {y:8s} -> back {to_alpaca(y)}")
