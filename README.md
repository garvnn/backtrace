# BackTrace

Compares backtested trading strategies against live paper trading execution to measure real-world performance differences.

## Overview

BackTrace runs the same strategies in two modes: **backtesting** on historical data and **live paper trading** via Alpaca. A dashboard and API support side-by-side comparison of backtest vs live results, Monte Carlo simulation for robustness, and automated daily execution across multiple tickers and strategies.

**Tech stack:** Python (backtest engine), FastAPI (API), SQLite (state), React + Recharts (dashboard), Alpaca API (paper trading), APScheduler (daily runs).

**Features:**
- Monte Carlo simulation on backtest equity curves
- Multi-strategy and multi-ticker support
- Automated daily execution at market close (4:30 PM ET)
- Backtest vs live performance comparison in one interface

## Strategies Implemented

1. **Momentum** — 6-month lookback: long when 6-month return is positive, otherwise flat/cash.
2. **MA Crossover** — 50/200-day moving average crossover: long when 50-day MA is above 200-day MA.
3. **Statistical Arbitrage** — Pairs trading on configured equity pairs (e.g. AAPL/MSFT, GOOGL/META) using spread mean reversion.

## Results

*(To be updated with actual data.)*

After [X] weeks of live trading ([Y] trades):

| Strategy       | Backtest | Live    | Difference |
|----------------|----------|---------|------------|
| Momentum       | +X.XX%   | +Y.YY%  | ±Z.ZZ%     |
| MA Crossover   | +X.XX%   | +Y.YY%  | ±Z.ZZ%     |
| Stat Arb       | +X.XX%   | +Y.YY%  | ±Z.ZZ%     |

**Analysis:** *(Objective explanation of observed differences once data is available.)*

## What This Demonstrates

- **Validation of backtests:** Backtest results are theoretical; live execution reveals whether they hold under real orders and market conditions.
- **Transaction costs and timing:** Execution costs and fill timing can change realized returns relative to backtest assumptions.
- **Real-world constraints:** Slippage, liquidity, and order execution differ from idealized backtest assumptions; comparing backtest vs live quantifies that gap.

## Technical Implementation

- **Backend:** FastAPI, SQLite (positions and run history), Alpaca API for paper orders and market data.
- **Frontend:** React, Recharts for equity curves and comparison charts.
- **Automation:** APScheduler triggers a daily job at 4:30 PM ET (after US market close); the job runs Momentum and MA Crossover on the top 10 SPY tickers and Stat Arb on configured pairs, then places orders for next-day execution.
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
   python visualization/plots.py
   python strategies/momentum.py
   python strategies/mean_reversion.py
   python analytics/metrics.py
   ```

2. **Live module (API + dashboard):**
   - Create `live/.env` with `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` (paper keys from [Alpaca](https://app.alpaca.markets/paper/dashboard/apis)).
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

### Deployment

Run the scheduler in the background with a process manager (e.g. systemd, screen, tmux) or a PaaS (e.g. Railway). Ensure the server timezone or cron is set for Eastern Time so the 4:30 PM ET run is correct. For the API and frontend, deploy FastAPI and the React build to your chosen host; keep `live/.env` and the SQLite DB path consistent.

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
