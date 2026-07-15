from __future__ import annotations

import random
import sys
import time

import httpx

from .. import config

# 429 sits below the 5xx line but is transient, so it is worth another try. Every other
# 4xx is a client error we would only reproduce by repeating it.
_RETRY_BELOW_500 = frozenset({429})


def _retry_after_s(resp: httpx.Response) -> float | None:
    """Seconds requested by a numeric Retry-After header, when the server sends one.
    The date form of the header is ignored — we fall back to our own backoff."""
    try:
        return float(resp.headers["retry-after"])
    except KeyError, ValueError:
        return None


def _backoff_s(attempt: int) -> float:
    """Exponential backoff with equal jitter, capped.

    Half the delay is fixed and half is random. The random half decorrelates us from
    every other client hammering the same recovering gateway; keeping the other half
    fixed guarantees the retry window actually widens, instead of collapsing into a
    burst that finishes before the outage does.
    """
    ceiling = min(config.HTTP_BACKOFF_CAP_S, config.HTTP_BACKOFF_BASE_S * 2**attempt)
    return ceiling / 2 + random.uniform(0, ceiling / 2)


def get_json(url: str, params: dict | None = None) -> dict:
    last_exc: Exception | None = None
    for attempt in range(config.HTTP_RETRIES):
        requested: float | None = None
        try:
            resp = httpx.get(url, params=params, timeout=config.HTTP_TIMEOUT_S)
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if resp.status_code < 500 and resp.status_code not in _RETRY_BELOW_500:
                resp.raise_for_status()  # raises on 4xx (not retried)
                return resp.json()
            last_exc = httpx.HTTPStatusError(
                f"server error {resp.status_code}", request=resp.request, response=resp
            )
            requested = _retry_after_s(resp)
        if attempt == config.HTTP_RETRIES - 1:
            break
        delay = requested if requested is not None else _backoff_s(attempt)
        # Log every retry: an unlogged retry is indistinguishable from no retry at all
        # when you are reading a failed CI run after the fact.
        print(
            f"http {url}: {last_exc}; retry {attempt + 2}/{config.HTTP_RETRIES} in {delay:.1f}s",
            file=sys.stderr,
        )
        time.sleep(delay)
    assert last_exc is not None
    raise last_exc
