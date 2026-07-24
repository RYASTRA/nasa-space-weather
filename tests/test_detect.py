"""Focused tests for relevance decisions that gate public alert Issues."""

from __future__ import annotations

import datetime as dt

from nasa_space_weather.detect import is_active
from nasa_space_weather.models import CME, EnlilRun


def test_undated_explicit_earth_impact_remains_actionable() -> None:
    cme = CME(
        activity_id="CME-IMPACT-NO-TIME",
        start_time=None,
        speed_kms=800.0,
        enlil=EnlilRun(arrival_time=None, predicted_kp=None, is_earth_gb=True),
        has_analysis=True,
    )
    assert is_active(cme, dt.datetime.now(dt.UTC))


def test_undated_non_impact_cme_is_not_assumed_active() -> None:
    cme = CME(
        activity_id="CME-MISS-NO-TIME",
        start_time=None,
        speed_kms=800.0,
        enlil=EnlilRun(arrival_time=None, predicted_kp=None, is_earth_gb=False),
        has_analysis=True,
    )
    assert not is_active(cme, dt.datetime.now(dt.UTC))
