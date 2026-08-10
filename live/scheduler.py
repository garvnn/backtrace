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

# Lookback days for strategy selector backtest (Momentum vs MA)
SELECTOR_LOOKBACK_DAYS = 60

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
    """Run one strategy per ticker (Momentum or MA Crossover) chosen by profit probability. Stat Arb is not run live."""
    from strategies.momentum import MomentumStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from executor import StrategyExecutor, SessionBudget
    from strategy_selector import select_strategy_for_ticker
    from trading_constants import BUYING_POWER_FRACTION

    log = _get_logger()
    log.info("Daily BackTrace job started")

    # Shared across every ticker in this run: caps total new-BUY dollars at
    # actual account cash, not the (possibly margin-leveraged) buying_power
    # each ticker would otherwise see independently. Seeded lazily from the
    # first ticker that gets far enough to have a live trading_client.
    session_budget = None

    for ticker in TOP_10_SPY:
        try:
            # Get data via executor (same source as live signals)
            executor = StrategyExecutor(MomentumStrategy(), ticker=ticker)
            data = executor.get_historical_data(days=SELECTOR_LOOKBACK_DAYS)
            if data is None or (hasattr(data, "empty") and data.empty) or len(data) < 30:
                log.warning("Skipping %s: insufficient data", ticker)
                continue

            (
                winner_class,
                prob_mom_tr,
                prob_ma_tr,
                prob_mom_val,
                prob_ma_val,
            ) = select_strategy_for_ticker(ticker, data, lookback_days=SELECTOR_LOOKBACK_DAYS)
            winner_name = winner_class().name
            log.info(
                "Chosen strategy for %s: %s (train prob M=%.2f MA=%.2f; val prob M=%.2f MA=%.2f)",
                ticker,
                winner_name,
                prob_mom_tr,
                prob_ma_tr,
                prob_mom_val,
                prob_ma_val,
            )

            if session_budget is None:
                try:
                    cash = float(executor.trading_client.get_account().cash)
                    session_budget = SessionBudget(cash * BUYING_POWER_FRACTION)
                    log.info("Session capital budget for this run: $%.2f (from account cash $%.2f)", session_budget.remaining, cash)
                except Exception as budget_err:
                    log.warning("Could not determine account cash for session budget cap; proceeding without a batch-level cap: %s", budget_err)

            # Run executor with winning strategy
            strategy = winner_class()
            if isinstance(strategy, MeanReversionStrategy):
                params = {"short_window": strategy.short_window, "long_window": strategy.long_window}
            else:
                params = {"lookback_period": strategy.lookback_period}
            executor = StrategyExecutor(strategy, ticker=ticker, params=params, session_budget=session_budget)
            executor.run()
            log.info("Completed %s on %s", strategy.name, ticker)
        except Exception as e:
            log.error(
                "Failed %s: %s\n%s",
                ticker,
                e,
                traceback.format_exc(),
            )

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
