"""
The one place that knows what a strategy is called.

Three spellings of the MA Crossover strategy were in circulation:

    "MA Crossover"    what the live executor writes to trades, and what the UI shows
    "MeanReversion"   what saved backtest_results rows are keyed on
    MeanReversionStrategy  the class, named after a strategy it is not

Six call sites reconciled those by hand - _normalize_strategy_for_db, an inline
ternary in /monte-carlo, inline branches in /backtest and /run-executor, an
alias set in analytics/divergence.py, and another in analytics/robustness.py -
each with its own slightly different idea of the mapping. The frontend had a
seventh, and got it wrong: App.js compared against 'MeanReversion' while the
executor wrote 'MA Crossover', so MA trades rendered as momentum trades.

Canonical spelling is the display name, "MA Crossover". "MeanReversion" is kept
readable as a legacy alias because production rows are stored under it: 27
saved backtests predate this rename and rewriting them would be rewriting
history rather than fixing code. New rows are written canonically.
"""

from __future__ import annotations

MOMENTUM = "Momentum"
MA_CROSSOVER = "MA Crossover"
STAT_ARB = "Stat Arb"

#: Legacy spelling -> canonical. Read side only; nothing writes these.
_LEGACY_ALIASES = {
    "meanreversion": MA_CROSSOVER,
    "mean reversion": MA_CROSSOVER,
    "mean_reversion": MA_CROSSOVER,
    "ma crossover": MA_CROSSOVER,
    "macrossover": MA_CROSSOVER,
    "momentum": MOMENTUM,
    "stat arb": STAT_ARB,
    "statarb": STAT_ARB,
    "stat_arb": STAT_ARB,
}

#: Spellings a stored row might use for a canonical strategy, for DB lookups
#: that must match both new and pre-rename rows.
_STORAGE_ALIASES = {
    MA_CROSSOVER: (MA_CROSSOVER, "MeanReversion"),
    MOMENTUM: (MOMENTUM,),
    STAT_ARB: (STAT_ARB,),
}


def canonical(strategy: str) -> str:
    """
    Any known spelling -> the canonical display name.

    Unrecognised names pass through unchanged: this normalises the spellings
    the project has actually used, it does not validate strategy names.
    """
    if not strategy:
        return MOMENTUM
    s = strategy.strip()
    return _LEGACY_ALIASES.get(s.lower(), s)


def storage_aliases(strategy: str) -> tuple[str, ...]:
    """
    Every spelling a stored row might use for this strategy, canonical first.

    Query with all of them, or pre-rename rows become invisible.
    """
    return _STORAGE_ALIASES.get(canonical(strategy), (canonical(strategy),))


def matches(stored: str, requested: str) -> bool:
    """True if a stored strategy string refers to the requested strategy."""
    return canonical(stored) == canonical(requested)
