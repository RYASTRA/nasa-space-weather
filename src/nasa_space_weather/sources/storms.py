"""DONKI GST endpoint: fetch geomagnetic storms over the configured window."""

from __future__ import annotations

import datetime as dt

from .. import config
from ..models import Storm, parse_storms
from .http import get_json


def _window() -> dict[str, str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=config.FETCH_LOOKBACK_DAYS)
    return {"startDate": start.isoformat(), "endDate": end.isoformat()}


def fetch() -> list[Storm]:
    """Fetch and parse geomagnetic storms in the look-back window."""
    params = {**_window(), "api_key": config.nasa_api_key()}
    return parse_storms(get_json(config.GST_API, params=params))
