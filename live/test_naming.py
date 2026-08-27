"""
Strategy-name canonicalisation and vendor symbol mapping.

Both cover bugs that were silent in production rather than loud:

  - the MA Crossover strategy answered to three different spellings, and the
    frontend compared against the one the executor does not write, so live MA
    trades rendered their parameters as a momentum strategy's.
  - BRK.B was sent to yfinance verbatim; Yahoo spells it BRK-B and returns an
    empty frame rather than raising, so one name in the ten-ticker universe had
    no backtest to compare its live trades against.
"""

import os
import sys

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from data.symbols import to_alpaca, to_yahoo
from strategies.naming import (
    MA_CROSSOVER,
    MOMENTUM,
    STAT_ARB,
    canonical,
    matches,
    storage_aliases,
)


def test_every_spelling_canonicalises_to_the_display_name():
    for spelling in ("MA Crossover", "MeanReversion", "mean_reversion", "MACrossover"):
        assert canonical(spelling) == MA_CROSSOVER, spelling
    assert canonical("Momentum") == MOMENTUM
    assert canonical("Stat Arb") == STAT_ARB


def test_canonical_is_idempotent():
    for name in (MA_CROSSOVER, MOMENTUM, STAT_ARB):
        assert canonical(canonical(name)) == canonical(name)


def test_unknown_names_pass_through():
    """This normalises known spellings; it is not a whitelist."""
    assert canonical("Some New Strategy") == "Some New Strategy"


def test_empty_defaults_to_momentum():
    assert canonical("") == MOMENTUM
    assert canonical(None) == MOMENTUM


def test_storage_aliases_include_the_legacy_spelling():
    """
    Pre-rename backtest rows are stored as "MeanReversion". A lookup that omits
    it silently reports "no backtest results" for a strategy that has 27 of them.
    """
    aliases = storage_aliases("MA Crossover")
    assert MA_CROSSOVER in aliases
    assert "MeanReversion" in aliases
    # Requesting by the legacy spelling must find the same set.
    assert set(storage_aliases("MeanReversion")) == set(aliases)


def test_storage_aliases_do_not_bleed_between_strategies():
    assert "MeanReversion" not in storage_aliases("Momentum")
    assert MA_CROSSOVER not in storage_aliases("Momentum")
    assert storage_aliases("Momentum") == (MOMENTUM,)


def test_matches_bridges_the_live_and_backtest_spellings():
    """The executor writes 'MA Crossover'; backtests stored 'MeanReversion'."""
    assert matches("MA Crossover", "MeanReversion")
    assert matches("MeanReversion", "MA Crossover")
    assert not matches("Momentum", "MA Crossover")


def test_class_share_symbols_map_to_yahoo():
    assert to_yahoo("BRK.B") == "BRK-B"
    assert to_yahoo("BF.B") == "BF-B"


def test_ordinary_symbols_are_unchanged():
    for sym in ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "UNH", "XOM", "SPY"):
        assert to_yahoo(sym) == sym, sym


def test_symbol_mapping_round_trips():
    for sym in ("AAPL", "BRK.B", "BF.B", "SPY"):
        assert to_alpaca(to_yahoo(sym)) == sym, sym


def test_symbol_mapping_normalises_case_and_whitespace():
    assert to_yahoo(" brk.b ") == "BRK-B"
    assert to_alpaca(" brk-b ") == "BRK.B"


def test_empty_symbol_is_not_an_error():
    assert to_yahoo("") == ""
    assert to_yahoo(None) is None


def test_whole_live_universe_maps_cleanly():
    """The scheduler's universe is the input that actually reaches the loader."""
    from scheduler import TOP_10_SPY

    for sym in TOP_10_SPY:
        mapped = to_yahoo(sym)
        assert "." not in mapped, f"{sym} -> {mapped} still carries Alpaca's class separator"
        assert to_alpaca(mapped) == sym, f"{sym} does not round-trip"

    # The one symbol in the universe that the mapping exists for.
    assert to_yahoo("BRK.B") == "BRK-B"
