"""
Retry policy and market-calendar gating.

Both cover gaps an audit flagged as "the first things a broker-side engineer
would grep for": zero occurrences of retry, backoff, 429 handling, or
get_calendar anywhere in the repo.
"""

import os
import sys
from datetime import date
from unittest.mock import MagicMock

import pytest

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

from alpaca_retry import (
    MAX_DELAY_SECONDS,
    backoff_delay,
    is_retryable,
    status_code_of,
    with_retry,
)
from market_calendar import UNKNOWN, describe_session, get_session, is_trading_day, next_trading_day


class FakeHTTPError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _no_sleep(_seconds):
    """Retry tests must not actually wait."""


def _fixed_rng(value=1.0):
    rng = MagicMock()
    rng.random.return_value = value
    return rng


# --- what counts as retryable -------------------------------------------------

@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retried(code):
    assert is_retryable(FakeHTTPError(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(code):
    """Repeating a 403 on an expired key just gets the same answer slower."""
    assert not is_retryable(FakeHTTPError(code))


def test_connection_failures_are_retried():
    """No status means the call never reached a decision."""
    assert is_retryable(TimeoutError("timed out"))
    assert is_retryable(ConnectionError("reset by peer"))


def test_status_code_read_from_nested_response():
    exc = Exception("boom")
    exc.response = MagicMock(status_code=503)
    assert status_code_of(exc) == 503
    assert is_retryable(exc)


def test_status_code_absent_is_none():
    assert status_code_of(Exception("no status")) is None


# --- retry behaviour ----------------------------------------------------------

def test_success_on_first_try_makes_one_call():
    call = MagicMock(return_value="ok")
    assert with_retry(call, sleep=_no_sleep) == "ok"
    assert call.call_count == 1


def test_retries_then_succeeds():
    call = MagicMock(side_effect=[FakeHTTPError(429), FakeHTTPError(503), "ok"])
    assert with_retry(call, sleep=_no_sleep) == "ok"
    assert call.call_count == 3


def test_gives_up_and_reraises_after_max_attempts():
    """
    Re-raise, never return a sentinel. A caller that cannot tell a failed
    account read from a zero balance is the fail-open pattern being removed.
    """
    call = MagicMock(side_effect=FakeHTTPError(503))
    with pytest.raises(FakeHTTPError):
        with_retry(call, max_attempts=3, sleep=_no_sleep)
    assert call.call_count == 3


def test_non_retryable_fails_immediately():
    call = MagicMock(side_effect=FakeHTTPError(403))
    with pytest.raises(FakeHTTPError):
        with_retry(call, sleep=_no_sleep)
    assert call.call_count == 1, "a 403 must not be retried"


def test_sleeps_between_attempts_and_backs_off():
    slept = []
    call = MagicMock(side_effect=[FakeHTTPError(429), FakeHTTPError(429), "ok"])
    with_retry(call, sleep=slept.append, rng=_fixed_rng(1.0))
    assert len(slept) == 2
    assert slept[1] > slept[0], "delay must grow"


def test_on_retry_hook_is_called_per_retry():
    seen = []
    call = MagicMock(side_effect=[FakeHTTPError(429), "ok"])
    with_retry(call, sleep=_no_sleep, on_retry=lambda a, e, d: seen.append((a, d)))
    assert len(seen) == 1


def test_backoff_is_jittered_and_bounded():
    assert backoff_delay(1) == 0.0, "first attempt never waits"
    low = backoff_delay(2, rng=_fixed_rng(0.0))
    high = backoff_delay(2, rng=_fixed_rng(1.0))
    assert 0 < low < high, "jitter must spread retries across callers"
    assert backoff_delay(50, rng=_fixed_rng(1.0)) <= MAX_DELAY_SECONDS


# --- market calendar ----------------------------------------------------------

def _calendar_client(entries):
    client = MagicMock()
    client.get_calendar.return_value = entries
    return client


def _day(d, open_="09:30", close="16:00"):
    entry = MagicMock()
    entry.date = d
    entry.open = open_
    entry.close = close
    return entry


def test_trading_day_returns_the_session():
    client = _calendar_client([_day(date(2026, 7, 6))])
    session = get_session(client, date(2026, 7, 6))
    assert session is not None
    assert session["date"] == date(2026, 7, 6)
    assert is_trading_day(client, date(2026, 7, 6))


def test_holiday_returns_none():
    """July 4th: Alpaca returns no calendar entry."""
    client = _calendar_client([])
    assert get_session(client, date(2026, 7, 3)) is None
    assert not is_trading_day(client, date(2026, 7, 3))


def test_describe_session_reports_closed():
    out = describe_session(_calendar_client([]), date(2026, 7, 3))
    assert out["status"] == "closed"
    assert out["is_trading_day"] is False


def test_describe_session_reports_half_day():
    """Day after Thanksgiving closes at 13:00 ET."""
    client = _calendar_client([_day(date(2026, 11, 27), close="13:00")])
    out = describe_session(client, date(2026, 11, 27))
    assert out["status"] == "open"
    assert out["is_half_day"] is True


def test_describe_session_marks_full_day():
    client = _calendar_client([_day(date(2026, 7, 6), close="16:00")])
    assert describe_session(client, date(2026, 7, 6))["is_half_day"] is False


def test_describe_session_never_raises_on_api_failure():
    """
    An unreadable calendar is reported as unknown, not as closed. Treating a
    metadata outage as a holiday would silently skip a real trading day.
    """
    client = MagicMock()
    client.get_calendar.side_effect = FakeHTTPError(403)
    out = describe_session(client, date(2026, 7, 6))
    assert out["status"] == UNKNOWN
    assert "error" in out


def test_get_session_raises_so_callers_decide():
    client = MagicMock()
    client.get_calendar.side_effect = FakeHTTPError(403)
    with pytest.raises(FakeHTTPError):
        get_session(client, date(2026, 7, 6))


def test_calendar_read_is_retried_on_transient_failure():
    client = MagicMock()
    client.get_calendar.side_effect = [FakeHTTPError(503), [_day(date(2026, 7, 6))]]
    assert is_trading_day(client, date(2026, 7, 6))
    assert client.get_calendar.call_count == 2


def test_next_trading_day_skips_the_weekend():
    friday = date(2026, 7, 3)
    monday = date(2026, 7, 6)
    client = _calendar_client([_day(monday)])
    assert next_trading_day(client, after=friday) == monday


def test_next_trading_day_none_when_calendar_empty():
    assert next_trading_day(_calendar_client([]), after=date(2026, 7, 3)) is None
