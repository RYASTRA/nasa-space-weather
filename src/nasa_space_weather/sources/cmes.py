from __future__ import annotations

import datetime as dt

from .. import config
from ..models import CME, parse_cmes
from .http import get_json


def _window() -> dict[str, str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=config.FETCH_LOOKBACK_DAYS)
    return {"startDate": start.isoformat(), "endDate": end.isoformat()}


def fetch() -> list[CME]:
    # /CME embeds cmeAnalyses[].enlilList[] — speed, isEarthGB, estimatedShockArrivalTime and
    # the kp_* predictions all arrive in this one response. That is why we do not also call
    # /CMEAnalysis or /WSAEnlilSimulations: they would re-fetch data we already hold.
    params = {**_window(), "api_key": config.nasa_api_key()}
    return parse_cmes(get_json(config.CME_API, params=params))
