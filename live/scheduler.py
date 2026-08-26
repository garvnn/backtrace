"""
Daily strategy executor - runs at market close (4:30 PM ET) on weekdays.

Runs one strategy per ticker (Momentum or MA Crossover) on top 10 SPY tickers. The strategy
is chosen per ticker by profit probability from a short lookback backtest. Stat Arb is not
run live; it remains available for backtesting only.
Logs to scheduler.log and console. Errors for one ticker do not stop the rest.

Usage:
  From project root:  python live/scheduler.py
  From live/:         python scheduler.py
Keeps running until interrupted (Ctrl+C). For background: nohup python live/scheduler.py & or use screen/tmux.
"""

import os
import sys
import logging
import traceback
from datetime import datetime, timedelta

# Ensure we run from live/ so .env and trading.db are found
LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != LIVE_DIR:
    os.chdir(LIVE_DIR)
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# Ticker universe (top 10 SPY holdings by weight)
TOP_10_SPY = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "BRK.B",
    "UNH",
    "XOM",
]

# Logging: file + console
LOG_FILE = os.path.join(LIVE_DIR, "scheduler.log")
_logger = None


def _get_logger():
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("backtrace_scheduler")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    _logger = logger
    return logger


def run_daily_strategy():
    """
    Run Momentum on every ticker in the universe. Stat Arb is not run live.

    Previously this asked strategy_selector.select_strategy_for_ticker to pick
    Momentum vs MA Crossover per ticker. That selector could not work: it fit on
    a 60-bar window split 70/30, giving 42 training rows, while Momentum needs a
    120-bar lookback and MA Crossover a 200-bar one. Both therefore produced
    all-zero signals, both profit probabilities came out exactly 0.00, the
    tie-break compared 0.0 to 0.0, and Momentum won by default - every ticker,
    every day. Production confirms it: 1,144 snapshots across 115 trading days
    are all tagged Momentum, and every log line reads
    "train prob M=0.00 MA=0.00; val prob M=0.00 MA=0.00".

    Removed rather than repaired. A meta-selector is a real idea, but it needs
    enough history to fit on and an out-of-sample test that can fail; adding one
    back is a deliberate piece of work, not a bug fix. Running one strategy
    honestly beats advertising a choice that never happened.
    """
    from strategies.momentum import MomentumStrategy
    from executor import StrategyExecutor, SessionBudget
    from trading_constants import BUYING_POWER_FRACTION

    log = _get_logger()
    log.info("Daily BackTrace job started")

    # Shared across every ticker in this run: caps total new-BUY dollars at
    # actual account cash, not the (possibly margin-leveraged) buying_power
    # each ticker would otherwise see independently. Seeded lazily from the
    # first ticker that gets far enough to have a live trading_client.
    session_budget = None

    # Kept so the run can take exactly one account-level snapshot at the end.
    last_executor = None

    # Settle the PREVIOUS run's orders before placing new ones. A DAY market
    # order submitted at 16:30 fills at the next open, ~17 hours later, so there
    # is nothing to poll at submit time - each run reconciles the last one.
    try:
        reconciler = StrategyExecutor(MomentumStrategy(), ticker=TOP_10_SPY[0])
        changes = reconciler.reconcile_open_orders()
        if changes:
            filled = [c for c in changes if (c["status"] or "").lower() == "filled"]
            log.info("Reconciled %d open order(s); %d now filled", len(changes), len(filled))
            for c in filled:
                if c["slippage"] is not None:
                    log.info(
                        "  %s %s: ref %.4f -> fill %.4f (slippage %+.4f)",
                        c["ticker"], c["side"], float(c["reference_price"]),
                        c["filled_avg_price"], c["slippage"],
                    )
        else:
            log.info("No open orders to reconcile")
    except Exception as recon_err:
        log.error("Order reconciliation failed (continuing to trade): %s", recon_err)

    for ticker in TOP_10_SPY:
        try:
            if session_budget is None:
                probe = StrategyExecutor(MomentumStrategy(), ticker=ticker)
                try:
                    cash = float(probe.trading_client.get_account().cash)
                    session_budget = SessionBudget(cash * BUYING_POWER_FRACTION)
                    log.info("Session capital budget for this run: $%.2f (from account cash $%.2f)", session_budget.remaining, cash)
                except Exception as budget_err:
                    log.warning("Could not determine account cash for session budget cap; proceeding without a batch-level cap: %s", budget_err)

            strategy = MomentumStrategy()
            params = {"lookback_period": strategy.lookback_period}
            executor = StrategyExecutor(strategy, ticker=ticker, params=params, session_budget=session_budget)
            executor.run()
            last_executor = executor
            log.info("Completed %s on %s", strategy.name, ticker)
        except Exception as e:
            log.error(
                "Failed %s: %s\n%s",
                ticker,
                e,
                traceback.format_exc(),
            )

    # One snapshot for the whole run, after every ticker has been processed.
    # A snapshot is account-level state, so taking it inside executor.run() wrote
    # one row per ticker - ten near-identical rows per trading day, which made
    # the equity curve's "daily" returns actually intra-run returns.
    if last_executor is not None:
        try:
            last_executor.log_portfolio_snapshot()
            log.info("Recorded end-of-run portfolio snapshot")
        except Exception as snap_err:
            log.error("Failed to record end-of-run snapshot: %s", snap_err)
    else:
        log.warning("No ticker completed; no snapshot recorded")

    log.info("Daily BackTrace job finished")


def run_test_job():
    """One-off test: run Momentum on AAPL to verify executor and logging."""
    from strategies.momentum import MomentumStrategy
    from executor import StrategyExecutor

    log = _get_logger()
    log.info("Test job started (Momentum on AAPL)")
    try:
        strategy = MomentumStrategy()
        executor = StrategyExecutor(strategy, ticker="AAPL")
        executor.run()
        executor.log_portfolio_snapshot()
        log.info("Test job completed successfully")
    except Exception as e:
        log.error("Test job failed: %s\n%s", e, traceback.format_exc())


if __name__ == "__main__":
    _get_logger()
    scheduler = BlockingScheduler()

    # 4:30 PM Eastern, Monday–Friday (after US market close)
    scheduler.add_job(
        run_daily_strategy,
        CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=30,
            timezone="America/New_York",
        ),
        id="daily_backtrace",
    )

    # Optional: uncomment to test scheduler without waiting for 4:30 PM (runs once in 1 min)
    # scheduler.add_job(
    #     run_test_job,
    #     "date",
    #     run_date=datetime.now() + timedelta(minutes=1),
    #     id="test_job",
    # )

    print(
        "BackTrace Live scheduler started. Runs daily at 4:30 PM ET (Mon–Fri). Ctrl+C to stop."
    )
    print(f"Logs: {LOG_FILE}")
    scheduler.start()
