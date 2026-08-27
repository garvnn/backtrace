# BackTrace

Compares backtested trading strategies against live paper trading execution to measure real-world performance differences.

## Overview

BackTrace runs the same strategy in two modes: **backtesting** on historical data (Yahoo) and **live paper trading** via Alpaca, then measures the gap between them. A dashboard and API support side-by-side comparison, Monte Carlo robustness testing, and automated daily execution across a ten-name universe.

The two vendors are deliberate. Backtesting on Yahoo and trading on Alpaca is what makes the vendor component of the backtest/live gap measurable at all — `analytics/divergence.py` pulls Alpaca bars specifically to quantify it against Yahoo's. The cost is a symbol-mapping layer (`data/symbols.py`), since the two disagree on how to spell a class share.

**Tech stack:** Python (backtest engine), FastAPI (API), SQLite (state), React + Recharts (dashboard), Alpaca API (paper trading), APScheduler (daily runs).

**Features:**
- Monte Carlo simulation on backtest equity curves
- Multi-strategy and multi-ticker support
- Automated daily execution at market close (4:30 PM ET)
- Backtest vs live performance comparison in one interface
- Execution decision logs (trade + no-trade reasons with diagnostics)

## Strategies Implemented

1. **Momentum** — 6-month lookback: long when 6-month return is positive, otherwise flat/cash.
2. **MA Crossover** — 50/200-day moving average crossover: long when 50-day MA is above 200-day MA.
3. **Statistical Arbitrage** — Pairs trading on configured equity pairs (e.g. AAPL/MSFT, GOOGL/META) using spread mean reversion. Backtest only.

Only Momentum runs live. The other two are available to backtest.

Note on naming: the MA Crossover strategy is trend-following (long while the fast MA is above
the slow one), not mean-reverting. It previously lived in `mean_reversion.py` as
`MeanReversionStrategy`, which is why backtest rows saved before the rename are keyed
`MeanReversion`; `strategies/naming.py` maps the spellings in one place.

## Results

### The live track record

Paper trading has run unattended on Railway since March 2026. As of **2026-08-25**:

| | |
|---|---|
| Trading days | 115 (2026-03-17 → 2026-08-25, no gaps) |
| Account snapshots | 1,144 |
| Orders submitted | 45 |
| Universe | 10 largest SPY holdings |
| Strategy | Momentum (120-day lookback), long/flat |
| Live return | **+1.68%** (103,621.03 → 105,366.19) |

The return is measured from the **first snapshot**, not from the configured $100,000 starting
capital. Those differ — the account had already drifted before the first snapshot was written —
and measuring against the configured number instead reported +5.37%, which is a real
+1.68% plus $3,621 of history that predates the record. `/performance` and `/live-benchmark`
now agree to eight decimal places because both measure the same window.

### The divergence figure

**Not yet reported.** The attribution machinery exists (`analytics/divergence.py`, with
confidence intervals from the block bootstrap in `analytics/robustness.py`), and the live equity
curve above is trustworthy — it is Alpaca's own account value, so it reflects whatever actually
filled. What is missing is *per-trade* attribution: all 45 orders were recorded at submission
and never polled again, so the trades table holds decision-time reference prices, not fills.
Reconciliation now runs at the start of each daily job, so trades from here forward carry a
terminal status and a real `filled_avg_price`; the 45 historical ones cannot be recovered.

The intended output, once enough reconciled trades accumulate:

```
Over N trading days, M reconciled trades, 10-name universe:
Momentum (120d) returned +A.A% live vs +B.B% backtested — a gap of −C.C% ± D.D%

Attribution:
  −x.x%   execution timing (T+1 open fills vs. same-bar close)
  −x.x%   transaction cost
  −x.x%   data vendor (Alpaca IEX vs. Yahoo consolidated closes)
  −x.x%   unexplained
```

No backtest number is quoted here yet, deliberately. The database holds 27 saved runs of
Momentum on AAPL over the same window reporting three different answers (+29.65% and +3.84%,
all at 49 trades) because the sizing code changed between them and nothing recorded which
version produced which row. Saved runs now carry a fingerprint of the code that produced them
and results from different code are no longer comparable; the number will be quoted once a run
under the current engine exists.

## Known gaps

Tracked honestly rather than described as working.

Open:

- Market data uses Alpaca's default feed (IEX on the free plan), not consolidated tape. This is
  one of the things the vendor-divergence analysis is meant to measure, but the code should say
  which feed it is on rather than relying on the server default.
- No market-hours or holiday gating (`get_clock` / `get_calendar` are not called).
- No retry or rate-limit handling on Alpaca calls.
- Live and backtest position sizing are implemented separately rather than sharing one module
  (contract written up in `docs/execution-layer-spec.md`; the module itself is not built).
- Stat Arb pair execution submits its two legs sequentially with no compensating action if the
  second is rejected. It is not run live, which is why this is not urgent.
- The live equity curve shows a 61% peak-to-trough drawdown that the +1.68% overall return does
  not explain. It survives daily-resampling, so it is not a snapshot-cadence artifact. Cause not
  yet established; it is not being reported as a strategy result until it is.

Closed recently:

- ~~Orders are never polled~~ — `reconcile_open_orders` settles the previous run's orders at the
  start of the next one, recording terminal status, `filled_qty`, `filled_avg_price` and signed
  slippage. A DAY market order submitted at 16:30 fills at the next open ~17 hours later, so
  there is nothing to poll at submit time.
- ~~The API is unauthenticated~~ — `POST /run-executor` and `DELETE /trades/{id}` require
  `X-API-Key` and default to denying when `BACKTRACE_API_KEY` is unset. CORS origins are
  configurable rather than `*`.
- ~~Per-ticker strategy selection~~ — advertised but never functioned: it fit on 42 training
  rows while the strategies need 120 and 200, so both scored exactly 0.00 and Momentum won the
  tie every time, for every ticker, across all 115 days. Removed rather than papered over.

## What This Demonstrates

- **Validation of backtests:** Backtest results are theoretical; live execution reveals whether they hold under real orders and market conditions.
- **Transaction costs and timing:** Execution costs and fill timing can change realized returns relative to backtest assumptions.
- **Real-world constraints:** Slippage, liquidity, and order execution differ from idealized backtest assumptions; comparing backtest vs live quantifies that gap.

## Technical Implementation

- **Backend:** FastAPI, SQLite (positions and run history), Alpaca API for paper orders and market data.
- **Frontend:** React, Recharts for equity curves and comparison charts.
- **Automation:** APScheduler triggers a daily job at 4:30 PM ET (after US market close); the job runs Momentum on the top 10 SPY tickers, then places DAY market orders that queue to the next open. Stat Arb and MA Crossover are backtest-only — the scheduler does not run them live.
- **Features:** Monte Carlo simulation (API endpoint), multi-ticker and multi-strategy runs, backtest engine with configurable transaction costs.

## Project Structure

```
backtrace/
├── data/              # Data loading and caching
├── strategies/        # Trading strategy implementations
├── engine/            # Backtesting execution engine
├── analytics/         # Performance metrics (Sharpe, drawdown, Monte Carlo)
├── visualization/     # Chart generation
├── live/              # Paper trading, API, scheduler, SQLite DB
├── frontend/          # React dashboard
└── results/           # Output charts
```

## Setup

### Installation

```bash
git clone https://github.com/garvnn/backtrace.git
cd backtrace
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

For the dashboard, install frontend dependencies:

```bash
cd frontend && npm install && cd ..
```

### Running locally

1. **Backtest only (no live trading):**
   ```bash
   python strategies/momentum.py
   python strategies/ma_crossover.py
   python analytics/metrics.py
   ```

2. **Live module (API + dashboard):**
   - Create `live/.env` with `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` (paper keys from [Alpaca](https://app.alpaca.markets/paper/dashboard/apis)).
   - Optional: `BACKTRACE_API_KEY` enables the write endpoints (`POST /run-executor`,
     `DELETE /trades/{id}`), which are otherwise disabled. Callers send it as `X-API-Key`.
     Leave it unset in a public deployment — a browser button cannot hold a secret, so the
     dashboard's "Run Strategy" button is deliberately inert there. The scheduler places the
     real trades on its own.
   - Optional: `ALLOWED_ORIGINS`, a comma-separated list of frontend origins. Defaults to `*`.
   - From project root:
     ```bash
     cd live && uvicorn api:app --reload
     ```
   - In another terminal, from project root:
     ```bash
     cd frontend && npm start
     ```
   - Open the dashboard (e.g. http://localhost:3000) and use the API (e.g. http://localhost:8000).

3. **Daily automated execution:**
   ```bash
   python live/scheduler.py
   ```
   Runs every weekday at 4:30 PM ET. To test without waiting, uncomment the optional test job in `live/scheduler.py` (runs once shortly after start), then comment it back out for production. Stop with **Ctrl+C**.

### Execution decision logs

The live executor records a decision log on every run, including no-trade outcomes.

- Table: `execution_logs` in the live SQLite DB
- API: `GET /execution-logs?strategy=Momentum&ticker=AAPL&limit=200`
- UI: Trades tab -> **Decision Logs**

Common `reason` values:

- `entry_buy_signal` / `exit_sell_signal`: a trade was executed
- `already_in_position` / `already_flat`: signal did not require a new order
- `signal_unchanged`: same side was already executed previously
- `qty_zero`: computed order quantity was 0
- `insufficient_data`: executor skipped due to missing bars
- `hold_state` / `already_in_target_position`: pair strategy stayed in current state

### Deployment

Run the scheduler in the background with a process manager (e.g. systemd, screen, tmux) or a PaaS (e.g. Railway). Ensure the server timezone or cron is set for Eastern Time so the 4:30 PM ET run is correct. For the API and frontend, deploy FastAPI and the React build to your chosen host; keep `live/.env` and the SQLite DB path consistent.

**Railway (API + scheduler in one service):** Use a single service with a volume mounted at `/data` and `DB_PATH=/data/trading.db`. Start command (run from project root so uvicorn can import the app):

```bash
python live/scheduler.py & exec uvicorn live.api:app --host 0.0.0.0 --port $PORT
```

**Vercel (frontend):** In Project Settings → Environment Variables, set `REACT_APP_API_URL` to your deployed API URL (e.g. `https://your-api.up.railway.app`). Otherwise the app defaults to `http://localhost:8000`, so visitors get a browser "Access other apps" prompt and the portfolio shows $0 until they allow (and only works if your machine is running the API).

## Metrics Calculated

- **Total return:** (Final value − Initial capital) / Initial capital
- **Sharpe ratio:** Annualized risk-adjusted return
- **Max drawdown:** Largest peak-to-trough decline
- **Number of trades:** Total buy/sell executions

## Author

Garv Narang — quantitative finance and market microstructure exploration.

## License

MIT
