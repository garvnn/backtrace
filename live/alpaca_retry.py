"""
Retry policy for Alpaca calls.

There was none. Every call to submit_order, get_account, get_all_positions and
get_stock_bars was unguarded, so a single transient 5xx aborted that ticker
mid-decision and the scheduler's blanket except logged it as "Failed TICKER".

Ten tickers x (bars + account + positions + order) per run is nowhere near
Alpaca's 200 requests/minute, so rate limiting is not what bites today. The
problem is that nothing distinguishes a transient failure from a real one, and
in an execution path that distinction decides whether retrying is safe.

What is retried, and what deliberately is not:

  429 and 5xx are retried with exponential backoff and jitter. These are the
  server saying "not now", which is a different statement from "no".

  4xx other than 429 is not retried. A 403 on an expired key, a 422 on an
  unshortable symbol, a 404 on a bad order id - repeating those produces the
  same answer more slowly.

  Order submission is retried too, but only because every order this system
  places carries a deterministic client_order_id. Alpaca rejects a duplicate,
  so a retry after a timeout cannot become a second position. Without that id
  a retry on submit_order would be genuinely dangerous, and this module would
  have to refuse it.

Jitter matters more than it looks: ten tickers failing against the same
degraded endpoint and backing off on identical schedules would retry in
lockstep and re-create the burst that caused the problem.
"""

from __future__ import annotations

import random
import time

try:
    from alpaca.common.exceptions import APIError
except ImportError:  # pragma: no cover - alpaca-py is a hard dependency
    APIError = None

#: Attempts in total, not retries after the first. 3 covers a brief blip
#: without holding the scheduler for minutes on a genuine outage.
DEFAULT_MAX_ATTEMPTS = 3

#: First backoff, doubling each attempt: 1s, 2s. Alpaca's limit resets per
#: minute, so a long sleep buys nothing a short one does not.
DEFAULT_BASE_DELAY_SECONDS = 1.0

#: Ceiling on any single sleep.
MAX_DELAY_SECONDS = 30.0

RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def status_code_of(exc) -> int | None:
    """
    HTTP status from an Alpaca exception, or None if it does not carry one.

    APIError exposes .status_code, but not always populated; some transport
    errors surface as plain requests exceptions with .response instead.
    """
    code = getattr(exc, "status_code", None)
    if code is not None:
        try:
            return int(code)
        except (TypeError, ValueError):
            return None
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (TypeError, ValueError):
                return None
    return None


def is_retryable(exc) -> bool:
    """
    Is this worth trying again?

    A status we recognise decides it. Without one - a socket timeout, a DNS
    blip, a connection reset - the call never reached a decision, so retrying
    is safe and usually right.
    """
    code = status_code_of(exc)
    if code is not None:
        return code in RETRYABLE_STATUS_CODES
    if APIError is not None and isinstance(exc, APIError):
        # An APIError with no parseable status is ambiguous; do not retry, since
        # Alpaca answered with something.
        return False
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def backoff_delay(attempt, base_delay=DEFAULT_BASE_DELAY_SECONDS, rng=None) -> float:
    """
    Seconds to wait before `attempt` (1-based; attempt 1 never waits).

    Exponential with full jitter. Ten tickers hitting the same degraded
    endpoint on identical schedules would retry in lockstep and rebuild the
    burst that caused the failure.
    """
    if attempt <= 1:
        return 0.0
    raw = min(base_delay * (2 ** (attempt - 2)), MAX_DELAY_SECONDS)
    draw = (rng or random).random()
    return raw * (0.5 + 0.5 * draw)


def with_retry(
    call,
    *,
    description="Alpaca call",
    max_attempts=DEFAULT_MAX_ATTEMPTS,
    base_delay=DEFAULT_BASE_DELAY_SECONDS,
    sleep=time.sleep,
    on_retry=None,
    rng=None,
):
    """
    Run `call()`, retrying transient failures.

    Re-raises the last exception once attempts are exhausted, rather than
    returning a sentinel: a caller that cannot tell a failed account read from
    a zero balance is exactly the fail-open pattern this codebase has been
    removing.
    """
    last_exc = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last_exc = exc
            if attempt >= max_attempts or not is_retryable(exc):
                raise
            delay = backoff_delay(attempt + 1, base_delay=base_delay, rng=rng)
            code = status_code_of(exc)
            message = (
                f"{description} failed (attempt {attempt}/{max_attempts}"
                f"{f', HTTP {code}' if code else ''}): {exc}. "
                f"Retrying in {delay:.1f}s"
            )
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            else:
                print(message)
            if delay:
                sleep(delay)
    # Unreachable: the loop either returns or raises.
    raise last_exc  # pragma: no cover
