"""
Daily strategy executor - runs at market close (4:30 PM ET) on weekdays.

Runs Momentum and MA Crossover on top 10 SPY tickers, plus Stat Arb on configured pairs.
Logs to scheduler.log and console. Errors for one ticker/pair do not stop the rest.

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

# Stat Arb pairs (must be valid in pairs_config; subset of TOP_10_SPY)
STAT_ARB_PAIRS = [
    ("AAPL", "MSFT"),
    ("GOOGL", "META"),
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
    """Run Momentum + MA Crossover on all tickers, then Stat Arb on configured pairs."""
    from strategies.momentum import MomentumStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.stat_arb import StatArbStrategy
    from executor import StrategyExecutor

    log = _get_logger()
    log.info("Daily BackTrace job started")

    # Single-ticker strategies: Momentum, MeanReversion (MA Crossover)
    for strategy_class in [MomentumStrategy, MeanReversionStrategy]:
        for ticker in TOP_10_SPY:
            try:
                strategy = strategy_class()
                executor = StrategyExecutor(strategy, ticker=ticker)
                executor.run()
                log.info("Completed %s on %s", strategy.name, ticker)
            except Exception as e:
                log.error(
                    "Failed %s on %s: %s\n%s",
                    strategy_class.__name__,
                    ticker,
                    e,
                    traceback.format_exc(),
                )

    # Stat Arb on configured pairs
    for ticker_a, ticker_b in STAT_ARB_PAIRS:
        try:
            strategy = StatArbStrategy(ticker_a, ticker_b)
            executor = StrategyExecutor(strategy, ticker=ticker_a)
            executor.run()
            log.info("Completed Stat Arb on %s / %s", ticker_a, ticker_b)
        except Exception as e:
            log.error(
                "Failed Stat Arb %s-%s: %s\n%s",
                ticker_a,
                ticker_b,
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
