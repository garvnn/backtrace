"""
Identity of the code that produces a backtest result.

A saved backtest is only comparable to another one if the code that produced
both was the same. That is not a theoretical concern here: the production
database holds 27 saved runs of Momentum on AAPL over 2020-01-01..2024-12-31,
and they report three different answers -

    id 20, 21, 22   ~ +29.65%   (differing in the 7th decimal)
    id 23, 24, 26, 27  +3.84%

all with n=49 trades. Identical trade counts and a 7.7x return spread means the
position sizing changed between runs, not the parameters - commit 4c2d59c,
"Cap batch position sizing against real cash", altered how much capital each
entry deploys. Nothing recorded which version of the engine produced which row.

/divergence-analysis then selected results[0] and compared live performance
against it, so which arbitrary row happened to sort first set the magnitude of
the project's headline number.

The fingerprint hashes every file whose contents change what a backtest returns.
Runs with different fingerprints are not comparable and should not be silently
mixed.
"""

from __future__ import annotations

import hashlib
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every file that can change a backtest's output. Sizing lives in the engine and
# in trading_constants; signal generation in strategies; the price series itself
# in the loader (adjustment settings, caching, vendor).
FINGERPRINTED_FILES = (
    "engine/backtest_engine.py",
    "strategies/base.py",
    "strategies/momentum.py",
    "strategies/mean_reversion.py",
    "strategies/stat_arb.py",
    "trading_constants.py",
    "data/loader.py",
)

_cached: str | None = None


def backtest_fingerprint(refresh: bool = False) -> str:
    """
    Short stable hash of the backtest-determining source files.

    Cached per process: these files do not change while the server runs, and a
    backtest run is not the place to be reading seven files off disk.
    """
    global _cached
    if _cached is not None and not refresh:
        return _cached

    h = hashlib.sha256()
    for rel in FINGERPRINTED_FILES:
        path = os.path.join(_ROOT, rel)
        h.update(rel.encode())
        try:
            with open(path, "rb") as f:
                h.update(f.read())
        except OSError:
            # A missing file is itself part of the identity - a run without
            # stat_arb.py is not the same as a run with it.
            h.update(b"<missing>")
    _cached = h.hexdigest()[:12]
    return _cached


if __name__ == "__main__":
    print(backtest_fingerprint())
    for rel in FINGERPRINTED_FILES:
        exists = os.path.isfile(os.path.join(_ROOT, rel))
        print(f"  {'ok ' if exists else 'MISSING'} {rel}")
