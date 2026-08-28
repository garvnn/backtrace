"""
Which pairs Stat Arb is allowed to trade, and which of them were actually tested.

This file used to open with "Pre-validated stock pairs" above a dictionary
grouped by sector. Nothing had validated them. MCD/YUM, WMT/TGT and META/SNAP
were asserted to be cointegrated because they are in the same industry, which
is a reasonable hypothesis and not a test.

Meanwhile live/pairs_finder.py runs a real Engle-Granger cointegration test
over a 20-name universe, computes hedge ratios, and writes its results to
pairs_output.json - and nothing imported it. The tool was built and never
connected, while the docstring claimed the work it would have done had been
done.

So: pairs_output.json, when present, is the validated set, and its p-values
travel with the pairs so a caller can see the evidence. The sector list stays
as a fallback, correctly labelled as untested. validated_pairs() reports which
is in use.

Regenerate with:  python live/pairs_finder.py
"""

from __future__ import annotations

import json
import os

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PAIRS_OUTPUT = os.path.join(LIVE_DIR, "pairs_output.json")

#: Hand-picked by sector. A hypothesis about which names should co-move, not a
#: result. Used only when no cointegration output is available, so that Stat
#: Arb still has a universe to backtest against.
SECTOR_CANDIDATES = {
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

_cache = None


def _load_validated():
    """
    Cointegration results from pairs_finder, or None if it has not been run.

    Cached per process. Returns a dict keyed by ticker, each value a list of
    {ticker, pvalue, beta} sorted by p-value, plus a flat lookup by pair.
    """
    global _cache
    if _cache is not None:
        return _cache

    if not os.path.isfile(PAIRS_OUTPUT):
        _cache = {"by_ticker": {}, "by_pair": {}, "source": "sector_candidates"}
        return _cache

    try:
        with open(PAIRS_OUTPUT) as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {PAIRS_OUTPUT} ({exc}); falling back to sector candidates")
        _cache = {"by_ticker": {}, "by_pair": {}, "source": "sector_candidates"}
        return _cache

    by_ticker: dict[str, list] = {}
    by_pair: dict[tuple, dict] = {}
    for row in rows or []:
        a = str(row.get("ticker_a", "")).upper()
        b = str(row.get("ticker_b", "")).upper()
        if not a or not b:
            continue
        meta = {
            "pvalue": row.get("pvalue"),
            "beta": row.get("beta"),
            "spread_mean": row.get("spread_mean"),
            "spread_std": row.get("spread_std"),
        }
        # Cointegration is symmetric; the hedge ratio is not, so only the
        # tested direction carries beta.
        by_ticker.setdefault(a, []).append({"ticker": b, **meta})
        by_ticker.setdefault(b, []).append({"ticker": a, **meta, "beta": None})
        by_pair[(a, b)] = meta
        by_pair[(b, a)] = {**meta, "beta": None}

    for entries in by_ticker.values():
        entries.sort(key=lambda e: (e["pvalue"] is None, e["pvalue"]))

    _cache = {
        "by_ticker": by_ticker,
        "by_pair": by_pair,
        "source": "cointegration" if by_pair else "sector_candidates",
    }
    return _cache


def get_available_pairs(ticker):
    """
    Valid pair options for a ticker, as a list of symbols.

    Prefers pairs that passed the cointegration test; falls back to the sector
    candidates when pairs_finder has not been run. Return shape is unchanged
    from before - the API and frontend consume a plain list.
    """
    if not ticker:
        return []
    sym = ticker.upper().strip()
    validated = _load_validated()["by_ticker"].get(sym)
    if validated:
        return [e["ticker"] for e in validated]
    return SECTOR_CANDIDATES.get(sym, [])


def get_pair_details(ticker):
    """
    Pair options with their evidence, for callers that want to show it.

    Each entry carries validated (bool) and, when tested, pvalue and beta.
    """
    if not ticker:
        return []
    sym = ticker.upper().strip()
    validated = _load_validated()["by_ticker"].get(sym)
    if validated:
        return [{"ticker": e["ticker"], "validated": True,
                 "pvalue": e["pvalue"], "beta": e["beta"]} for e in validated]
    return [{"ticker": t, "validated": False, "pvalue": None, "beta": None}
            for t in SECTOR_CANDIDATES.get(sym, [])]


def is_valid_pair(ticker_a, ticker_b):
    """Is this a pair the system will trade?"""
    if not ticker_a or not ticker_b:
        return False
    a, b = ticker_a.upper().strip(), ticker_b.upper().strip()
    if a == b:
        return False
    return b in get_available_pairs(a)


def pair_evidence(ticker_a, ticker_b):
    """
    What is known about this pair: its cointegration p-value, or nothing.

    Returns None when the pair was never tested - which is the honest answer
    for every entry in SECTOR_CANDIDATES.
    """
    if not ticker_a or not ticker_b:
        return None
    key = (ticker_a.upper().strip(), ticker_b.upper().strip())
    return _load_validated()["by_pair"].get(key)


def validated_pairs():
    """
    Where the current universe comes from, so a reader is not left guessing.

    source is "cointegration" when pairs_finder output is in use, or
    "sector_candidates" when it is the untested fallback.
    """
    state = _load_validated()
    return {
        "source": state["source"],
        "output_file": PAIRS_OUTPUT if state["source"] == "cointegration" else None,
        "pair_count": len(state["by_pair"]) // 2 if state["by_pair"] else sum(
            len(v) for v in SECTOR_CANDIDATES.values()
        ),
        "note": (
            "Pairs passed an Engle-Granger cointegration test; run "
            "python live/pairs_finder.py to refresh."
            if state["source"] == "cointegration" else
            "Hand-picked by sector and NOT tested for cointegration. Run "
            "python live/pairs_finder.py to replace these with tested pairs."
        ),
    }
