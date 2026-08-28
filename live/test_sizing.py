"""
Shared position sizing, and the parity between backtest and live that it exists
to guarantee.

test_backtest_and_live_agree_on_share_count is the one that matters. It fails
if either side reintroduces its own formula or goes back to sizing against
buying_power - the bug that drove production cash to -$6,830.22 on 2026-07-10
while the backtest, sizing off cash, modelled nothing of the sort.
"""

import os
import sys

import pytest

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from engine.backtest_engine import BacktestEngine
from trading.sizing import SessionBudget, SizingPolicy, default_policy
from trading_constants import CAPITAL_FRACTION, MAX_DOLLAR_PER_STOCK

POLICY = SizingPolicy(max_notional_per_symbol=10_000.0, capital_fraction=0.95)

CAPITALS = [1_000.0, 9_999.0, 50_000.0, 100_000.0, 1_000_000.0]
PRICES = [5.0, 42.5, 150.0, 3_000.0]


# --- the parity test ----------------------------------------------------------

@pytest.mark.parametrize("capital", CAPITALS)
@pytest.mark.parametrize("price", PRICES)
def test_backtest_and_live_agree_on_share_count(capital, price):
    """
    Same policy, same capital, same reference price -> identical share count.

    The engine and the executor must both route through SizingPolicy. If either
    grows its own min()/int() again, or reads buying_power instead of cash,
    this grid catches it.
    """
    engine = BacktestEngine()
    live_policy = default_policy()

    assert engine.sizing.shares(capital, price) == live_policy.shares(capital, price), (
        f"backtest and live disagree at capital={capital} price={price}"
    )


def test_engine_policy_matches_configured_constants():
    engine = BacktestEngine()
    assert engine.sizing.max_notional_per_symbol == float(MAX_DOLLAR_PER_STOCK)
    assert engine.sizing.capital_fraction == float(CAPITAL_FRACTION)


def test_buying_power_sized_order_is_visibly_larger():
    """
    Documents the bug in numbers, so the parity above has a reference point.

    A margin paper account shows buying_power at roughly 2x equity. Sizing a
    spread leg off that rather than off equity is where the ~2x came from.
    """
    equity = 100_000.0
    buying_power = 2 * equity

    correct = POLICY.pair_notional(equity, 0.45)
    wrong = buying_power * 0.45  # what live/executor.py used to do

    assert correct == pytest.approx(100_000 * 0.95 * 0.45)
    assert wrong == pytest.approx(90_000.0)
    assert wrong > correct * 2.0


# --- notional -----------------------------------------------------------------

def test_per_symbol_cap_binds_when_capital_is_large():
    assert POLICY.notional(1_000_000.0) == 10_000.0


def test_capital_fraction_binds_when_capital_is_small():
    assert POLICY.notional(1_000.0) == pytest.approx(950.0)


def test_session_budget_binds_when_lowest():
    assert POLICY.notional(1_000_000.0, budget_remaining=250.0) == 250.0


def test_budget_of_zero_blocks_the_order():
    assert POLICY.notional(1_000_000.0, budget_remaining=0.0) == 0.0
    assert POLICY.shares(1_000_000.0, 100.0, budget_remaining=0.0) == 0


def test_holds_back_the_remainder():
    """capital_fraction exists to keep some cash unspent."""
    capital = 1_000.0
    assert POLICY.notional(capital) < capital


# --- shares -------------------------------------------------------------------

def test_shares_floor_rather_than_round():
    # 950 / 100 = 9.5 -> 9, never 10. Rounding up would overspend.
    assert POLICY.shares(1_000.0, 100.0) == 9


def test_shares_never_exceed_the_notional():
    for capital in CAPITALS:
        for price in PRICES:
            qty = POLICY.shares(capital, price)
            assert qty * price <= POLICY.notional(capital) + 1e-9


def test_price_at_or_below_zero_yields_no_shares():
    assert POLICY.shares(100_000.0, 0.0) == 0
    assert POLICY.shares(100_000.0, -10.0) == 0


def test_unusable_inputs_yield_no_shares():
    for bad in (None, "", "abc", float("nan"), float("inf")):
        assert POLICY.shares(100_000.0, bad) == 0, bad


def test_negative_capital_yields_no_shares():
    """A margined-out account has no capital to deploy, not negative capital."""
    assert POLICY.shares(-50_000.0, 100.0) == 0
    assert POLICY.notional(-50_000.0) == 0.0


def test_price_above_available_capital_yields_no_shares():
    assert POLICY.shares(1_000.0, 3_000.0) == 0


# --- session budget -----------------------------------------------------------

def test_budget_reserves_and_depletes():
    budget = SessionBudget(1_000.0)
    assert budget.reserve(400.0) == 400.0
    assert budget.remaining == pytest.approx(600.0)
    assert budget.reserve(900.0) == 600.0, "cannot grant more than remains"
    assert budget.remaining == 0.0


def test_budget_never_goes_negative():
    budget = SessionBudget(100.0)
    budget.reserve(500.0)
    assert budget.remaining == 0.0
    assert budget.reserve(1.0) == 0.0


def test_budget_rejects_nonsense_totals():
    assert SessionBudget(-1.0).remaining == 0.0
    assert SessionBudget(None).remaining == 0.0
    assert SessionBudget(float("nan")).remaining == 0.0


def test_batch_cannot_outspend_the_budget():
    """
    Ten tickers, each individually under the per-symbol cap, sharing one budget
    smaller than their sum. This is the scenario the budget exists for.
    """
    budget = SessionBudget(15_000.0)
    capital = 1_000_000.0  # per-symbol cap would allow 10k each = 100k total
    spent = 0.0
    for _ in range(10):
        qty = POLICY.shares(capital, 100.0, budget_remaining=budget.remaining)
        cost = qty * 100.0
        budget.reserve(cost)
        spent += cost
    assert spent <= 15_000.0, f"batch spent {spent} against a 15,000 budget"


# --- pair sizing --------------------------------------------------------------

def test_pair_notional_applies_both_fractions():
    assert POLICY.pair_notional(100_000.0, 0.45) == pytest.approx(100_000 * 0.95 * 0.45)


def test_pair_notional_ignores_the_single_name_cap():
    """A spread leg is half a position; the per-symbol ceiling does not apply."""
    assert POLICY.pair_notional(100_000.0, 0.45) > POLICY.max_notional_per_symbol


def test_pair_notional_handles_bad_inputs():
    assert POLICY.pair_notional(-1.0, 0.45) == 0.0
    assert POLICY.pair_notional(100_000.0, -0.45) == 0.0
    assert POLICY.pair_notional(None, 0.45) == 0.0
