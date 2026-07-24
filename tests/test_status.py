"""Tests for the Observatory status.json contract (schema 1).

The tile is a compressed retelling of the page: the same recent-storm and
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


def _earthbound_cme(arrives_in_h: float, activity_id: str = "CME-001") -> CME:
    return CME(
        activity_id=activity_id,
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


def test_recent_storm_headline_and_no_recent_fallback() -> None:
    episodes, events = _wire([_storm(6.0)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    assert doc["headline"] == "Recent geomagnetic storm — max Kp 7"

    quiet = status.build([], {}, _now(), sources_ok=True)
    assert quiet["headline"] == "No recent geomagnetic storms"
    assert quiet["items"] == []


def test_recent_storm_without_kp_is_pending_not_absent() -> None:
    episodes, events = _wire([_storm(2.0, max_kp=None)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    assert doc["headline"] == "Recent geomagnetic storm — Kp pending"
    assert any(item["text"] == "Geomagnetic storm — Kp pending" for item in doc["items"])


def test_contract_envelope() -> None:
    doc = status.build([], {}, _now(), sources_ok=True)
    assert doc["schema"] == 1
    assert doc["project"] == "nasa-space-weather"
    assert doc["site"] == "https://ryastra.github.io/nasa-space-weather/"
    assert doc["fresh_for_hours"] == 3
    assert doc["updated_utc"].endswith("Z")
    assert doc["ok"] is True
    assert 1 <= len(doc["metrics"]) <= 4


def test_degraded_sources_override_reassuring_headline() -> None:
    doc = status.build([], {}, _now(), sources_ok=False)
    assert doc["ok"] is False
    assert doc["headline"] == "DONKI data incomplete"
    assert all(metric["value"] == "Unknown" for metric in doc["metrics"])


def test_flare_metric_counts_last_7_days_only() -> None:
    episodes, events = _wire([_flare(48.0, "M2.6"), _flare(24 * 10, "X1.0"), _flare(2.0, "C9.9")])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {m["label"]: m["value"] for m in doc["metrics"]}
    assert metrics["M+X flares · 7d"] == "1"  # the C-class and the 10-day-old X don't count
    assert all("C9.9" not in item["text"] for item in doc["items"])


def test_earthbound_cme_becomes_metric_and_item() -> None:
    episodes, events = _wire([_earthbound_cme(arrives_in_h=30.0)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {m["label"]: m["value"] for m in doc["metrics"]}
    assert doc["headline"] == "Earth-arrival forecast active — predicted Kp 6"
    assert metrics["Future CME arrival forecasts"] == "1"
    assert metrics["Recent CME model times · 72h"] == "0"
    arrival_items = [i for i in doc["items"] if "CME arrival" in i["text"]]
    assert len(arrival_items) == 1
    assert arrival_items[0]["text"].startswith("CME arrival forecast")
    assert "Kp 6" in arrival_items[0]["text"]
    assert arrival_items[0]["url"] == "https://example.test/cme"
    # when_utc is rendered beside the text — the text must not repeat it
    assert "UTC" not in arrival_items[0]["text"]


def test_recent_and_stale_cme_arrivals_are_counted_separately() -> None:
    events_in = [
        _earthbound_cme(arrives_in_h=-12.0, activity_id="CME-RECENT"),
        _earthbound_cme(arrives_in_h=-73.0, activity_id="CME-STALE"),
    ]
    episodes, events = _wire(events_in)
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {m["label"]: m["value"] for m in doc["metrics"]}
    assert metrics["Future CME arrival forecasts"] == "0"
    assert metrics["Recent CME model times · 72h"] == "1"

    arrival_items = [i for i in doc["items"] if "CME arrival" in i["text"]]
    assert len(arrival_items) == 1
    assert arrival_items[0]["text"].startswith("Recent modelled CME arrival time")
    assert "arrived" not in arrival_items[0]["text"].lower()


def test_duplicate_shock_uses_strongest_prediction_in_status() -> None:
    arrival = _now() + dt.timedelta(hours=20)
    mild = CME(
        activity_id="CME-MILD",
        start_time=_now() - dt.timedelta(hours=8),
        speed_kms=900.0,
        enlil=EnlilRun(arrival, 3.0, True),
        has_analysis=True,
    )
    fierce = CME(
        activity_id="CME-FIERCE",
        start_time=_now() - dt.timedelta(hours=6),
        speed_kms=700.0,
        enlil=EnlilRun(arrival, 7.0, True),
        has_analysis=True,
    )
    episodes, events = _wire([mild, fierce])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    arrival_items = [item for item in doc["items"] if "CME arrival" in item["text"]]
    assert len(arrival_items) == 1
    assert "Kp 7" in arrival_items[0]["text"]


def test_eta_pending_earth_impact_is_visible_without_timestamps() -> None:
    cme = CME(
        activity_id="CME-ETA-PENDING",
        start_time=None,
        speed_kms=800.0,
        enlil=EnlilRun(None, None, True),
        has_analysis=True,
        link="https://example.test/eta-pending",
    )
    episodes, events = _wire([cme])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {metric["label"]: metric["value"] for metric in doc["metrics"]}
    assert doc["headline"] == "Earth impact expected — CME arrival time pending"
    assert metrics["Earth impacts · ETA pending"] == "1"
    assert doc["items"][0] == {
        "text": "Earth impact expected — CME arrival time pending",
        "url": "https://example.test/eta-pending",
    }


def test_linked_eta_pending_catalog_records_count_as_one_impact() -> None:
    start = _now() - dt.timedelta(hours=4)
    cmes = [
        CME(
            activity_id=f"CME-ETA-PENDING-{index}",
            start_time=start,
            speed_kms=700.0 + index,
            enlil=EnlilRun(None, None, True),
            has_analysis=True,
        )
        for index in (1, 2)
    ]
    episodes, events = _wire(cmes)
    doc = status.build(episodes, events, _now(), sources_ok=True)
    metrics = {metric["label"]: metric["value"] for metric in doc["metrics"]}
    matching = [
        item
        for item in doc["items"]
        if item["text"] == "Earth impact expected — CME arrival time pending"
    ]
    assert metrics["Earth impacts · ETA pending"] == "1"
    assert len(matching) == 1


def test_partial_status_keeps_known_impact_in_the_headline() -> None:
    cme = CME(
        activity_id="CME-PARTIAL-IMPACT",
        start_time=None,
        speed_kms=800.0,
        enlil=EnlilRun(None, None, True),
        has_analysis=True,
    )
    episodes, events = _wire([cme])
    doc = status.build(episodes, events, _now(), sources_ok=False)
    assert doc["ok"] is False
    assert doc["headline"] == ("Earth impact expected — CME arrival time pending · data incomplete")


def test_partial_status_keeps_a_known_future_forecast_in_the_headline() -> None:
    episodes, events = _wire([_earthbound_cme(12.0)])
    doc = status.build(episodes, events, _now(), sources_ok=False)
    assert doc["headline"] == ("Earth-arrival forecast active — predicted Kp 6 · data incomplete")


def test_known_storm_headline_discloses_another_pending_kp_series() -> None:
    episodes, events = _wire([_storm(8.0, 5.0), _storm(2.0, None)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    assert doc["headline"] == (
        "Recent geomagnetic storm — max known Kp 5; another storm has Kp pending"
    )
    assert any(item["text"] == "Geomagnetic storm — Kp pending" for item in doc["items"])


def test_items_are_bounded_and_newest_first() -> None:
    flares = [_flare(float(h), "M1.0") for h in (1, 2, 3, 4, 5, 6, 7)]
    episodes, events = _wire([*flares, _storm(10.0)])
    doc = status.build(episodes, events, _now(), sources_ok=True)
    assert len(doc["items"]) == 5
    whens = [i["when_utc"] for i in doc["items"]]
    assert whens == sorted(whens, reverse=True)
    assert all(len(i["text"]) <= 140 for i in doc["items"])


def test_nearest_future_arrivals_survive_the_five_item_limit() -> None:
    cmes = [_earthbound_cme(float(hours), f"CME-{hours}") for hours in (6, 12, 18, 24, 30, 36)]
    episodes, events = _wire(cmes)
    doc = status.build(episodes, events, _now(), sources_ok=True)
    whens = [item["when_utc"] for item in doc["items"]]
    expected = [
        cme.enlil.arrival_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        for cme in cmes
        if cme.enlil is not None and cme.enlil.arrival_time is not None
    ]
    assert len(whens) == 5
    assert whens == expected[:5]


def test_render_site_writes_status_json_beside_index(tmp_path: Path) -> None:
    render_site([], {}, tmp_path, sources_ok=False)
    doc = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert doc["ok"] is False
    assert (tmp_path / "index.html").exists()
