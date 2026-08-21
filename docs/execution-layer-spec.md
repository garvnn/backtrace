# Execution layer spec

Working document for the two modules that make the project's central measurement trustworthy.
Delete this file once both are implemented and tested.

The project's deliverable is one attributed number: how far live paper returns diverged from the
backtest, and why. Both modules below exist because that number is currently unmeasurable —
not because they are good practice in the abstract.

---

## Module 1 — `trading/sizing.py` (shared position sizing)

### Why

`BacktestEngine` and `StrategyExecutor` currently compute share counts with two different
formulas against two different capital bases:

| | capital base | formula |
|---|---|---|
| `engine/backtest_engine.py:170-177` (pair) | `equity` | `equity * 0.95 * 0.45` ≈ 0.43 × equity |
| `live/executor.py:345-347` (pair) | `buying_power` | `buying_power * 0.45` ≈ 0.90 × equity at 2x margin |
| `engine/backtest_engine.py:102` (single) | `cash` | `min(10_000, cash * 0.95)` |
| `live/executor.py:207` (single) | `buying_power` | `min(10_000, buying_power * 0.95)` |

The single-name paths agree today only because the $10,000 cap binds in both. They diverge the
moment it doesn't. The pair paths differ by roughly 2x right now.

If backtest and live size differently, the divergence you measure is your own sizing bug, not
market reality. Every line of the attribution table would be wrong for a boring reason. This is
why it's module 1.

### Contract

```python
@dataclass(frozen=True)
class SizingPolicy:
    max_notional_per_symbol: float   # MAX_DOLLAR_PER_STOCK
    capital_fraction: float          # BUYING_POWER_FRACTION — rename; it is not buying power

    def notional(self, available_capital: float, budget_remaining: float | None = None) -> float:
        """Dollars to deploy. Capped by max_notional_per_symbol, capital_fraction, and
        (when batching) the shared budget. Never negative."""

    def shares(self, available_capital: float, reference_price: float,
               budget_remaining: float | None = None) -> int:
        """Whole shares. reference_price is the price the DECISION was made at
        (prior close), not the expected fill price. Returns 0 if price <= 0."""
```

### Invariants

1. **`available_capital` is cash or equity. Never `buying_power`.** `buying_power` is a margin
   allowance, not money you have. `scripts/check_alpaca.py` now prints the `BP/equity` ratio so
   you can see the multiple you'd be picking up.
2. **Both callers pass the same reference price semantics** — the prior close. The backtest
   already does (`ref_close = closes.iloc[i-1]`); live already does (`data['Close'].iloc[-1]`).
   Preserve that; it is one of the things this project gets right.
3. Integer shares, floor, never negative.
4. Pure function. No clients, no I/O, no globals — so it is trivially testable.

### Wiring

- `engine/backtest_engine.py`: replace the inline `min(...)` / `int(dollar / ref_close)` in
  `run`, `run_buyhold`, and `pair_capital` with `policy.shares(...)`.
- `live/executor.py`: replace the `buying_power` reads. Use `float(account.cash)`.
- Rename `BUYING_POWER_FRACTION` in `trading_constants.py` — the name is what caused the bug.
  `CAPITAL_FRACTION` or `MAX_CAPITAL_DEPLOYED_FRACTION`.
- `SessionBudget` moves here too; it's a sizing concern, not an executor concern.

### The test that matters

A parity test. Same policy, same capital, same price → backtest and live must return the
identical share count. Assert it across a grid (capital: 1k/50k/100k/1M, price: 5/150/3000).

This is the test that would have caught the 2x gap, and it's the one to write first.

---

## Module 2 — order lifecycle in `live/executor.py`

### Why

`submit_order` is called and the order is never looked at again. So:

- `trades.price` holds the **prior close**, not the fill price (`executor.py:232`). The SELL path
  stores no price at all.
- `trades.status` is `str(order.status)` captured at submission — permanently
  `OrderStatus.PENDING_NEW`. `frontend/src/App.js:437` has a `partially_filled` label that is
  unreachable, and strips the `"OrderStatus."` prefix off a leaked Python enum repr.
- Partial fills, rejections, and expirations are invisible.

Your live equity curve therefore isn't attributable to real fills, so the divergence number can't
be decomposed. This is the blocker on the whole deliverable.

### The insight that makes this tractable

The reason this is usually skipped: you submit at 16:30, the order won't fill until 09:30 the next
morning, you realise you can't poll synchronously, and you give up.

**Don't poll synchronously. Reconcile at the start of the next run.** Orders are asynchronous
facts about the world; you record the intent now and settle it later. Structure:

```
scheduler run:
  1. reconcile_open_orders()   <-- settles yesterday's fills FIRST
  2. for each ticker: decide, submit, record intent
```

`reconcile_positions.py` already has the right instinct at the position level. This is the same
idea at the order level.

### Contract

```python
def submit_and_record(self, symbol, qty, side, *, reference_price, signal_ts) -> str:
    """Submit a market DAY order, persist the intent, return order_id.
    Records: order_id, client_order_id, symbol, side, submitted_qty, reference_price,
             signal_ts, fill_model, status, submitted_at.
    Does NOT record a fill price — none exists yet."""

def reconcile_open_orders(self) -> list[dict]:
    """For every trade row in a non-terminal status, fetch get_order_by_id and update
    filled_qty, filled_avg_price, status, reconciled_at. Returns what changed."""
```

Terminal statuses: `filled`, `canceled`, `expired`, `rejected`. Everything else is open.
Non-terminal rows older than ~2 trading days should be logged loudly — that means something
is wrong, not that the order is patient.

### Schema additions to `trades`

`submitted_qty`, `filled_qty`, `filled_avg_price`, `reference_price`, `client_order_id`,
`fill_model`, `signal_ts`, `submitted_at`, `reconciled_at`.

Keep the existing `ALTER TABLE ... except OperationalError: pass` idiom in `database.py:34` for
each new column — it's ugly but it's already the pattern and it preserves your live data. Don't
reset the DB; those snapshots are your measurement period.

### Two details that carry real weight

**`client_order_id` for idempotency.** Pass
`client_order_id=f"{strategy}-{symbol}-{date}-{side}"`. Alpaca rejects duplicates, so a
double-fired scheduler run cannot double-submit. Right now the only protection is the
`get_last_executed_signal` DB check — which fails open if the DB write succeeded but the
process died, and doesn't protect against two processes at once. Broker-enforced beats
self-enforced.

**`fill_model` tag.** At submit time, call `get_clock()`. Record either:
- `queued_next_open` — market closed, order queues to the next open. Matches the backtest's
  Open[T+1] model.
- `immediate_intraday` — market open (i.e. someone hit the dashboard's Run button at 11am).
  The signal came off a *partial* daily bar and filled same-session. **The backtest cannot
  reproduce this trade under any of its models.**

Without this tag, intraday manual runs silently contaminate your measurement and you'd never
know which trades to exclude. With it, `estimate_execution_timing_impact` in
`analytics/divergence.py:249` — which already exists and already computes exactly this
correction — can finally be applied to the right subset.

This one field is what connects the execution layer to the thesis.

### Store the enum properly

`order.status.value`, not `str(order.status)`. Then delete the `.replace('OrderStatus.', '')`
calls at `App.js:432` and `:449`.

---

## What I'm handling in parallel

Deleting the strategy selector and the live Stat Arb path, the `MeanReversionStrategy` →
`MovingAverageCrossoverStrategy` rename plus the four normalization sites it spawned, the
`BRK.B` ↔ `BRK-B` symbol mapping, converting the tests to pytest, `pyproject.toml`, and the
`os.chdir` removal in `api.py`.

I'll leave `execute_signal` and the sizing call sites structurally intact so you're not
rebasing onto a moving target. If you want a specific boundary — e.g. I stub the module with
signatures and failing tests and you fill in the bodies — say so.

## Verification, end to end

1. `pytest` green, and the sizing parity test genuinely fails if you reintroduce
   `buying_power` on either side.
2. `python scripts/check_alpaca.py` — confirm the `BP/equity` ratio is what you expect.
3. One real scheduler run. Then, the next morning, `reconcile_open_orders()` and check that
   `filled_avg_price` is populated and differs from `reference_price` — that difference is
   slippage, and it's the first real datum for the attribution table.
4. `python live/reconcile_positions.py` clean against the paper account.
