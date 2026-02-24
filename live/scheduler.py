"""
Daily strategy executor - runs at market close (4:30 PM ET) on weekdays.

Usage:
  From project root:  python live/scheduler.py
  From live/:         python scheduler.py
Keeps running until interrupted (Ctrl+C). For background: nohup python live/scheduler.py & or use screen/tmux.

Cron alternative (run executor once daily without keeping a process up):
  30 16 * * 1-5 cd /path/to/backtrace/live && /path/to/venv/bin/python executor.py
(4:30 PM ET weekdays; adjust path and timezone to your system.)
"""

import os
import sys

# Ensure we run from live/ so .env and trading.db are found
LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != LIVE_DIR:
    os.chdir(LIVE_DIR)
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


def run_daily_strategy():
    """Run the momentum strategy once (same as executor.py main)."""
    from strategies.momentum import MomentumStrategy
    from executor import StrategyExecutor
    strategy = MomentumStrategy()
    executor = StrategyExecutor(strategy, ticker="AAPL")
    executor.run()


if __name__ == "__main__":
    scheduler = BlockingScheduler()
    # 4:30 PM Eastern, Monday–Friday (after US market close)
    scheduler.add_job(
        run_daily_strategy,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone="America/New_York"),
        id="daily_backtrace",
    )
    print("BackTrace Live scheduler started. Runs daily at 4:30 PM ET (Mon–Fri). Ctrl+C to stop.")
    scheduler.start()
