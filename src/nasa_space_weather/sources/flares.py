from __future__ import annotations

import datetime as dt

from .. import config
from ..models import Flare, parse_flares
from .http import get_json


def _window() -> dict[str, str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=config.FETCH_LOOKBACK_DAYS)
    return {"startDate": start.isoformat(), "endDate": end.isoformat()}


def fetch() -> list[Flare]:
    params = {**_window(), "api_key": config.nasa_api_key()}
    return parse_flares(get_json(config.FLR_API, params=params))
