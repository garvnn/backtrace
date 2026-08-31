"""
Is the market actually open today?

The scheduler fires on a Mon-Fri cron, which includes Thanksgiving, July 4th,
Christmas, and every other NYSE holiday. On those days the run proceeds
normally: it fetches bars (the most recent one is stale), generates a signal
off it, and submits orders that queue to the next real session. The
idempotency check usually prevents an actual duplicate trade, so the
consequence has been mild - but "usually saved by a different mechanism" is
not the same as correct, and a broker-side engineer will look for
get_calendar() specifically.

Half-days matter too, and are easier to get wrong than holidays. The market
closes at 13:00 ET on the day after Thanksgiving and Christmas Eve. A
scheduler that fires at 16:30 is three and a half hours after the close on
those days rather than half an hour, so the daily bar it reads is complete
but the assumptions around timing shift. Recording the session's real close
time is cheaper than rediscovering this later from a strange fill.

Deliberately not cached across runs. The scheduler runs once a day, so a
lookup costs one request against a 200/minute limit, and a stale holiday
calendar is a worse failure than a redundant call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

try:
    from alpaca.trading.requests import GetCalendarRequest
except ImportError:  # pragma: no cover - alpaca-py is a hard dependency
    GetCalendarRequest = None

from alpaca_retry import with_retry

#: Returned when the calendar cannot be read at all.
UNKNOWN = "unknown"


def get_session(trading_client, on_date=None):
    """
    The trading session for `on_date` (default today), or None if closed.

    Returns a dict with date, open and close as the broker reports them, so a
    caller can see a half-day rather than inferring one. Returns None when the
    date is a weekend or a holiday.

    Raises if the calendar cannot be read. Callers decide whether an unknown
    calendar should stop a run; guessing "probably open" inside here would be
    the fail-open pattern this codebase has been removing.
    """
    if GetCalendarRequest is None:  # pragma: no cover
        raise RuntimeError("alpaca-py is required to read the market calendar")

    day = on_date or date.today()
    request = GetCalendarRequest(start=day, end=day)
    days = with_retry(
        lambda: trading_client.get_calendar(request),
        description=f"get_calendar({day})",
    )
    for entry in days or []:
        entry_date = getattr(entry, "date", None)
        if entry_date is None:
            continue
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()
        if entry_date == day:
            return {
                "date": entry_date,
                "open": getattr(entry, "open", None),
                "close": getattr(entry, "close", None),
            }
    return None


def is_trading_day(trading_client, on_date=None) -> bool:
    """True if the given date is a NYSE session. Raises if unreadable."""
    return get_session(trading_client, on_date) is not None


def describe_session(trading_client, on_date=None) -> dict:
    """
    Session status for logging and for the execution decision record.

    Never raises: returns status UNKNOWN with the error attached when the
    calendar cannot be read, so a scheduler can log the fact and make its own
    call about whether to proceed.
    """
    day = on_date or date.today()
    try:
        session = get_session(trading_client, day)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return {"date": str(day), "status": UNKNOWN, "error": str(exc)}

    if session is None:
        return {"date": str(day), "status": "closed", "is_trading_day": False}

    out = {
        "date": str(session["date"]),
        "status": "open",
        "is_trading_day": True,
        "session_open": str(session["open"]) if session["open"] else None,
        "session_close": str(session["close"]) if session["close"] else None,
    }
    out["is_half_day"] = _is_half_day(session["close"])
    return out


def _is_half_day(close_time) -> bool | None:
    """
    Does this session close before the usual 16:00 ET?

    close_time is whatever the broker returned - a time, a datetime, or a
    string. Returns None when it cannot be read rather than guessing.
    """
    if close_time is None:
        return None
    hour = getattr(close_time, "hour", None)
    if hour is None:
        text = str(close_time)
        # "13:00" or "1899-12-30 13:00:00"
        for part in text.replace("T", " ").split():
            if ":" in part:
                try:
                    hour = int(part.split(":")[0])
                    break
                except ValueError:
                    continue
    if hour is None:
        return None
    return hour < 16


def next_trading_day(trading_client, after=None, search_days=10):
    """
    The next session strictly after `after` (default today), or None.

    Used to say when a queued order will actually fill - "queues to the next
    open" is only informative if the date is named, and over a long weekend it
    is not the next calendar day.
    """
    start = (after or date.today()) + timedelta(days=1)
    end = start + timedelta(days=search_days)
    if GetCalendarRequest is None:  # pragma: no cover
        raise RuntimeError("alpaca-py is required to read the market calendar")

    request = GetCalendarRequest(start=start, end=end)
    days = with_retry(
        lambda: trading_client.get_calendar(request),
        description=f"get_calendar({start}..{end})",
    )
    for entry in sorted(days or [], key=lambda e: str(getattr(e, "date", ""))):
        entry_date = getattr(entry, "date", None)
        if entry_date is None:
            continue
        if hasattr(entry_date, "date"):
            entry_date = entry_date.date()
        if entry_date >= start:
            return entry_date
    return None
