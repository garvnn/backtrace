# BackTrace Live — Verification Checklist

Use this checklist to verify the system before running unsupervised.

---

## 1. Database Integrity

Run: `cd live && python test_database.py`

- [ ] All tables exist: `trades`, `portfolio_snapshots`, `backtest_results`, `pair_trades`
- [ ] Insert/retrieve works for each table
- [ ] Timestamps stored correctly
- [ ] Edge cases: null params, special characters (e.g. BRK.B), empty positions

---

## 2. Executor Full Test

Run: `cd live && python test_executor.py`

- [ ] All 10 SPY tickers run (with mocked Alpaca so no real orders)
- [ ] Data fetch and signal generation work per ticker
- [ ] Trade placement is mocked (no live orders)
- [ ] Database logging verified
- [ ] Error handling: bad ticker, API failure

---

## 3. Strategy Selector Validation

Run: `cd live && python test_strategy_selector.py`

- [ ] 60-day backtest for Momentum and MA Crossover on sample data
- [ ] Profit probability calculation correct
- [ ] Tie-breaking when probabilities equal (uses total return)
- [ ] Insufficient/empty data defaults to Momentum
- [ ] Multiple tickers produce consistent (non-random) selection

---

## 4. API Endpoint Testing

Run: `cd live && python test_api.py`

- [ ] `/` — root message
- [ ] `/portfolio` — format and data accuracy
- [ ] `/trades` — all trades, optional `strategy` filter
- [ ] `/portfolio-history` — chronological, optional `strategy` filter
- [ ] `/performance` — metrics shape and filter
- [ ] `/backtest-results` — list, optional `ticker`/`strategy` filters
- [ ] `/monte-carlo` — runs or returns error if no backtest
- [ ] `/available-pairs/{ticker}` — pairs list
- [ ] `/pairs`, `/pair-trades` — structure
- [ ] `DELETE /trades/{id}` — 404 for missing id
- [ ] CORS headers present
- [ ] `POST /backtest`, `POST /run-executor` — acceptable status codes

---

## 5. Scheduler Verification

Run: `cd live && python test_scheduler.py`

- [ ] Timezone is US/Eastern (America/New_York)
- [ ] Cron: 4:30 PM weekdays (Mon–Fri)
- [ ] Logging to `scheduler.log` and console
- [ ] Error in one ticker does not crash scheduler (loop try/except)
- [ ] Weekends skipped (next fire is weekday)

Optional manual: Uncomment the 1-minute test job in `scheduler.py`, run `python scheduler.py`, confirm job runs once, then comment it back out.

---

## 6. Frontend Data Flow

**Data refresh:**
- [ ] Frontend fetches on load
- [ ] Auto-refresh every 60 seconds works
- [ ] No memory leaks after 10+ refreshes
- [ ] Loading states display correctly
- [ ] Error states handle API failures
- [ ] All number formatting correct
- [ ] Charts render without errors
- [ ] Tab switching doesn’t break state

---

## 7. Edge Case Testing

| Scenario | Expected behavior |
|---------|-------------------|
| **Market closed** | Executor runs on last available data; no crash |
| **API rate limit** | Alpaca throttles; executor should handle/retry or fail gracefully |
| **Network failure** | Exception caught; scheduler continues to next ticker |
| **Partial fills** | Logged with actual fill qty/price when available from Alpaca |
| **Order rejection** | Alpaca returns error; executor should log and not crash |
| **Insufficient funds** | Order may be rejected by Alpaca; executor caps at MAX_DOLLAR_PER_STOCK |
| **Missing data** | Executor skips ticker (e.g. “insufficient data”) |
| **Database corruption** | Restore from backup; DB is file-based (e.g. `trading.db`) |

---

## 8. Position Reconciliation

Run: `cd live && python reconcile_positions.py`

- [ ] Fetches positions from Alpaca API
- [ ] Fetches latest snapshot from DB
- [ ] Compares quantities and flags mismatches
- [ ] Report printed (or “Alpaca unavailable” if no keys)

---

## 9. Performance Validation

- [ ] Sharpe ratio: manually check one sample vs `analytics.metrics.calculate_metrics`
- [ ] Max drawdown: formula (cumulative vs running max) matches `metrics.py`
- [ ] Total return: (final - initial) / initial
- [ ] Monte Carlo: requires enough return periods (e.g. ≥21); no division by zero
- [ ] No division by zero in performance endpoint when history length &lt; 2

---

## 10. Security Check

- [ ] `.env` and `live/.env` in `.gitignore`
- [ ] No API keys in git history
- [ ] Database file (`*.db` or `live/trading.db`) gitignored
- [ ] No sensitive data in frontend (keys only in backend env)
- [ ] CORS: currently `allow_origins=["*"]`; tighten for production if needed

---

## Success Criteria

**System is ready for unsupervised run when:**

- All automated tests pass (`test_database`, `test_executor`, `test_strategy_selector`, `test_api`, `test_scheduler`)
- Edge cases are understood and handled
- Reconciliation shows no unexplained mismatches (or Alpaca not used)
- Secrets are secured and CORS is acceptable for deployment

After running all tests, generate `VERIFICATION_REPORT.md` with date, pass/fail per test, issues found, and confidence level (1–10).
