"""Tests for the Observatory status.json contract (schema 1).

The tile is a compressed retelling of the page: the same active-storm and
Earth-directed-CME semantics as site.py, never a new interpretation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from nasa_space_weather import status
from nasa_space_weather.episodes import Episode, Member
from nasa_space_weather.models import CME, EnlilRun, Flare, Storm
from nasa_space_weather.site import render_site


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _flare(hours_ago: float, class_type: str = "M2.6") -> Flare:
    flr_id = f"FLR-{hours_ago}"
    return Flare(
        flr_id=flr_id,
        peak_time=_now() - dt.timedelta(hours=hours_ago),
        class_type=class_type,
        active_region=14473,
        link="https://example.test/flr",
    )


def _storm(hours_ago: float, max_kp: float | None = 7.0) -> Storm:
    return Storm(
        gst_id=f"GST-{hours_ago}",
        start_time=_now() - dt.timedelta(hours=hours_ago),
        max_kp=max_kp,
        link="https://example.test/gst",
    )


def _earthbound_cme(arrives_in_h: float) -> CME:
    return CME(
        activity_id="2026-07-22T00:00:00-CME-001",
        start_time=_now() - dt.timedelta(hours=12),
        speed_kms=900.0,
        enlil=EnlilRun(
            arrival_time=_now() + dt.timedelta(hours=arrives_in_h),
            predicted_kp=6.0,
            is_earth_gb=False,
        ),
        has_analysis=True,
        link="https://example.test/cme",
    )


def _wire(events: list[Flare | Storm | CME]) -> tuple[list[Episode], dict]:
    def _id(e) -> str:
        return getattr(e, "flr_id", None) or getattr(e, "gst_id", None) or e.activity_id

    members = [Member(_id(e), type(e).__name__, "info") for e in events]
    episode = Episode(key="episode:test", members=members, severity="info")
    return [episode], {_id(e): e for e in events}


def test_active_storm_headline_and_quiet_fallback() -> None:
    episodes, events = _wire([_storm(6.0)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    assert doc["headline"] == "Geomagnetic storm — Kp 7"

    quiet = status.build([], {}, _now(), sources_ok=True)
    assert quiet["headline"] == "Geomagnetically quiet"
    assert quiet["items"] == []


def test_contract_envelope() -> None:
    doc = status.build([], {}, _now(), sources_ok=True)
    assert doc["schema"] == 1
    assert doc["project"] == "nasa-space-weather"
    assert doc["site"] == "https://ryastra.github.io/nasa-space-weather/"
    assert doc["fresh_for_hours"] == 3
    assert doc["updated_utc"].endswith("Z")
    assert 1 <= len(doc["metrics"]) <= 4


def test_flare_metric_counts_last_7_days_only() -> None:
    episodes, events = _wire([_flare(48.0, "M2.6"), _flare(24 * 10, "X1.0"), _flare(2.0, "C9.9")])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {m["label"]: m["value"] for m in doc["metrics"]}
    assert metrics["M+X flares · 7d"] == "1"  # the C-class and the 10-day-old X don't count


def test_earthbound_cme_becomes_metric_and_item() -> None:
    episodes, events = _wire([_earthbound_cme(arrives_in_h=30.0)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {m["label"]: m["value"] for m in doc["metrics"]}
    assert metrics["CME arrivals pending"] == "1"
    arrival_items = [i for i in doc["items"] if "CME arrival" in i["text"]]
    assert len(arrival_items) == 1
    assert "Kp 6" in arrival_items[0]["text"]
    assert arrival_items[0]["url"] == "https://example.test/cme"
    # when_utc is rendered beside the text — the text must not repeat it
    assert "UTC" not in arrival_items[0]["text"]


def test_items_are_bounded_and_newest_first() -> None:
    flares = [_flare(float(h), "M1.0") for h in (1, 2, 3, 4, 5, 6, 7)]
    episodes, events = _wire([*flares, _storm(10.0)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    assert len(doc["items"]) == 5
    whens = [i["when_utc"] for i in doc["items"]]
    assert whens == sorted(whens, reverse=True)
    assert all(len(i["text"]) <= 140 for i in doc["items"])


def test_render_site_writes_status_json_beside_index(tmp_path: Path) -> None:
    render_site([], {}, tmp_path, sources_ok=False)
    doc = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert doc["ok"] is False
    assert (tmp_path / "index.html").exists()
