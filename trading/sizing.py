"""
How many shares to buy. One implementation, used by both the backtest and the
live executor.

They used to compute this separately, against different capital bases:

    backtest single  min(10_000, cash * 0.95)                  / prior close
    live single      min(10_000, buying_power * 0.95)          / prior close
    backtest pair    equity * 0.95 * 0.45         ~ 0.43x equity
    live pair        buying_power * 0.45          ~ 0.90x equity at 2x margin

The single-name paths agreed only because the $10,000 cap bound on both sides.
The pair paths differed by roughly 2x outright.

That is not a tidiness problem. This project exists to measure how far live
returns diverge from the backtest and attribute the gap to execution timing,
transaction cost, and data vendor. If the two sides also size differently, the
gap being measured is partly a sizing bug, and every line of the attribution
table is wrong for a boring reason.

It was not hypothetical either. Production went cash-negative - -$6,830.22 on
2026-07-10 - because the executor sized against buying_power, which on a margin
paper account is roughly twice equity. The backtest never models that.

    buying_power is a margin allowance, not money you have.

That distinction is the whole reason this module exists, so the parameter is
named available_capital and the callers pass cash or equity. The old constant
was called BUYING_POWER_FRACTION, which is exactly the name that invited the
bug; it is CAPITAL_FRACTION now.

Pure functions, no clients, no I/O, no globals - so the parity test between the
two callers is trivial to write, and it is the test that matters here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizingPolicy:
    """
    The risk limits that decide an order's size.

    max_notional_per_symbol: hard dollar ceiling on any one name.
    capital_fraction:        share of available capital that may be deployed,
                             holding the rest back.
    """

    max_notional_per_symbol: float
    capital_fraction: float

    def notional(self, available_capital, budget_remaining=None) -> float:
        """
        Dollars to deploy on one symbol. Never negative.

        available_capital must be cash or equity - never buying_power.

        budget_remaining is the shared ceiling for a batch of tickers processed
        in one run (see SessionBudget). Without it, ten independently-capped
        buys can collectively spend more real cash than the account holds, with
        no single buy ever looking oversized.
        """
        capital = _non_negative(available_capital)
        allowed = min(self.max_notional_per_symbol, capital * self.capital_fraction)
        if budget_remaining is not None:
            allowed = min(allowed, _non_negative(budget_remaining))
        return max(0.0, allowed)

    def shares(self, available_capital, reference_price, budget_remaining=None) -> int:
        """
        Whole shares to order, floored, never negative.

        reference_price is the price the DECISION was taken at - the prior
        close - not the expected fill price. Both callers already use the prior
        close (the backtest as closes.iloc[i-1], live as Close.iloc[-1]) and
        both fill at the next open. Keeping the reference consistent is what
        makes their share counts comparable at all.
        """
        try:
            price = float(reference_price)
        except (TypeError, ValueError):
            return 0
        if not math.isfinite(price) or price <= 0:
            return 0
        dollars = self.notional(available_capital, budget_remaining)
        if not math.isfinite(dollars):
            return 0
        return max(0, int(dollars // price))

    def pair_notional(self, available_capital, pair_fraction) -> float:
        """
        Per-leg dollars for a two-legged spread.

        Applies capital_fraction first, then pair_fraction, matching what the
        backtest already did (equity * 0.95 * 0.45). The live path applied only
        pair_fraction, and to buying_power rather than equity, which is where
        the 2x came from.

        max_notional_per_symbol is deliberately not applied: it is a
        single-name limit, and a spread leg is half a position, not a position.
        """
        base = _non_negative(available_capital) * self.capital_fraction
        return max(0.0, base * _non_negative(pair_fraction))


class SessionBudget:
    """
    Shared ceiling on new BUY dollars across one batch of tickers.

    Seeded from account cash, not buying_power, so a ten-ticker run cannot
    collectively draw margin the backtest never models. Lives here rather than
    in the executor because it is a sizing concern.
    """

    def __init__(self, total):
        self.remaining = _non_negative(total)

    def reserve(self, amount) -> float:
        """Deduct up to `amount`. Returns what was actually deducted."""
        wanted = _non_negative(amount)
        granted = min(wanted, self.remaining)
        self.remaining -= granted
        return granted


def _non_negative(value) -> float:
    """Floats that are NaN, None, or negative are treated as no capital."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(out) or out < 0:
        return 0.0
    return out


def default_policy() -> SizingPolicy:
    """The policy both the backtest and live execution use unless overridden."""
    from trading_constants import CAPITAL_FRACTION, MAX_DOLLAR_PER_STOCK

    return SizingPolicy(
        max_notional_per_symbol=float(MAX_DOLLAR_PER_STOCK),
        capital_fraction=float(CAPITAL_FRACTION),
    )
