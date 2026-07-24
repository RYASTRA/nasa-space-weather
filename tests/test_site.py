"""Tests for the static Space-Weather Watch site.

The four no-arrival CME states must stay distinguishable on the page (the models.py
invariant: never let 'analysed, harmless' and 'not yet analysed' look the same to a
reader — and never let either look like 'impact expected, ETA unknown')."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from nasa_space_weather.episodes import Episode, Member
from nasa_space_weather.models import CME, EnlilRun, Flare, Storm
from nasa_space_weather.site import render_site


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _cme(
    activity_id: str = "2026-07-16T12:00:00-CME-001",
    *,
    start_h_ago: float = 6.0,
    has_analysis: bool = False,
    enlil: EnlilRun | None = None,
    speed: float | None = None,
) -> CME:
    return CME(
        activity_id=activity_id,
        start_time=_now() - dt.timedelta(hours=start_h_ago),
        speed_kms=speed,
        enlil=enlil,
        has_analysis=has_analysis,
    )


def _page_for(cmes: list[CME], tmp_path: Path, severity: str = "info") -> str:
    members = [Member(c.activity_id, "CME", severity) for c in cmes]
    episode = Episode(key=f"episode:{cmes[0].activity_id}", members=members, severity=severity)
    path = render_site([episode], {c.activity_id: c for c in cmes}, tmp_path)
    return path.read_text(encoding="utf-8")


def test_writes_an_index_html(tmp_path: Path) -> None:
    path = render_site([], {}, tmp_path)
    assert path.name == "index.html"
    page = path.read_text(encoding="utf-8")
    assert "Space-Weather Watch" in page
    assert '<html lang="en">' in page
    assert 'href="assets/site.css"' in page
    assert "Last check healthy" in page
    assert "data-feed-health" in page
    assert "data-stale-warning" in page
    assert (tmp_path / "assets" / "site.css").exists()
    assert (tmp_path / "assets" / "site.js").exists()


def test_failed_sources_never_masquerade_as_quiet_conditions(tmp_path: Path) -> None:
    page = render_site([], {}, tmp_path, sources_ok=False).read_text(encoding="utf-8")
    assert "DONKI data is incomplete for this check" in page
    assert "Arrival outlook unavailable" in page
    assert "Conditions cannot be confirmed" in page
    assert "Nothing inbound." not in page
    assert "Geomagnetically quiet." not in page
    assert "metric-health--degraded" in page
    assert page.count("<dd>Unknown</dd>") == 3


# --- the four no-arrival states -------------------------------------------------


def test_unanalysed_cme_names_the_missing_analysis(tmp_path: Path) -> None:
    page = _page_for([_cme(has_analysis=False)], tmp_path)
    assert "arrival prediction not yet available" in page
    assert "not yet analysed" in page
    assert "CME forecast pending" in page
    assert "No Earth arrival forecast" not in page


def test_analysed_cme_with_no_enlil_run_names_the_missing_model_run(tmp_path: Path) -> None:
    page = _page_for([_cme(has_analysis=True, enlil=None)], tmp_path)
    assert "arrival prediction not yet available" in page
    assert "no WSA-Enlil run yet" in page
    assert "CME forecast pending" in page


def test_analysed_cme_predicted_to_miss_earth_says_so_not_prediction_pending(
    tmp_path: Path,
) -> None:
    miss = EnlilRun(arrival_time=None, predicted_kp=None, is_earth_gb=False)
    page = _page_for([_cme(has_analysis=True, enlil=miss)], tmp_path)
    assert "not currently predicted to reach Earth" in page
    # The prediction exists and says "miss" — the page must not call it unavailable.
    assert "not yet available" not in page


def test_earth_bound_cme_without_an_eta_shouts_impact_expected_not_pending(
    tmp_path: Path,
) -> None:
    earth_bound = EnlilRun(arrival_time=None, predicted_kp=None, is_earth_gb=True)
    page = _page_for([_cme(has_analysis=True, enlil=earth_bound)], tmp_path, severity="high")
    assert "Earth impact expected" in page
    assert "shock arrival time not yet estimated" in page
    assert "not yet available" not in page
    assert "Earth impact expected · ETA pending" in page
    assert "No Earth arrival forecast" not in page


# --- forward-looking gating -----------------------------------------------------


def test_stale_analysed_miss_is_dropped_from_the_forward_looking_page(tmp_path: Path) -> None:
    miss = EnlilRun(arrival_time=None, predicted_kp=None, is_earth_gb=False)
    page = _page_for([_cme(start_h_ago=100.0, has_analysis=True, enlil=miss)], tmp_path)
    assert "Nothing inbound." in page


def test_stale_unanalysed_cme_is_dropped_from_the_forward_looking_page(tmp_path: Path) -> None:
    page = _page_for([_cme(start_h_ago=100.0)], tmp_path)
    assert "Nothing inbound." in page


# --- behaviours that must not regress -------------------------------------------


def test_incoming_arrival_is_listed_with_its_timestamp(tmp_path: Path) -> None:
    arrival = _now() + dt.timedelta(hours=30)
    run = EnlilRun(arrival_time=arrival, predicted_kp=6.0, is_earth_gb=True)
    page = _page_for([_cme(has_analysis=True, enlil=run)], tmp_path, severity="high")
    assert "<h4>Expected <time" in page
    assert "Future WSA-Enlil model times from the last hourly check" in page
    assert arrival.strftime("%Y-%m-%d %H:%M UTC") in page
    assert "No recent storm recorded" in page
    assert "Aurora should remain confined" not in page


def test_a_past_model_time_is_not_presented_as_an_observed_arrival(tmp_path: Path) -> None:
    arrival = _now() - dt.timedelta(hours=10)
    run = EnlilRun(arrival_time=arrival, predicted_kp=3.0, is_earth_gb=True)
    page = _page_for([_cme(start_h_ago=60.0, has_analysis=True, enlil=run)], tmp_path, "high")
    assert "Recent modelled arrival times" in page
    assert "<h4>Forecast time <time" in page
    assert "Arrived" not in page


def test_earth_impact_without_eruption_time_stays_visible(tmp_path: Path) -> None:
    earth_bound = EnlilRun(arrival_time=None, predicted_kp=None, is_earth_gb=True)
    cme = _cme(has_analysis=True, enlil=earth_bound)
    cme.start_time = None
    page = _page_for([cme], tmp_path, severity="high")
    assert "Earth impact expected · ETA pending" in page
    assert "unknown eruption time" in page
    assert "Time unknown" in page
    assert "Earth-relevant CME" in page
    assert "No high-signal activity in seven days" not in page
    assert "Nothing inbound." not in page
    assert "No Earth arrival forecast" not in page


def test_linked_cmes_sharing_one_pending_state_render_one_row(tmp_path: Path) -> None:
    first = _cme("2026-07-16T12:00:00-CME-001", has_analysis=True, enlil=None)
    second = _cme("2026-07-16T12:00:00-CME-002", has_analysis=True, enlil=None)
    second.start_time = first.start_time  # same eruption seen twice in the catalog
    page = _page_for([first, second], tmp_path)
    assert page.count("no WSA-Enlil run yet") == 1


def test_unlinked_cmes_sharing_a_timestamp_keep_separate_assessments(tmp_path: Path) -> None:
    first = _cme("CME-ONE", has_analysis=True, enlil=None)
    second = _cme("CME-TWO", has_analysis=True, enlil=None)
    second.start_time = first.start_time
    episodes = [
        Episode(
            key="episode:one",
            members=[Member(first.activity_id, "CME", "info")],
            severity="info",
        ),
        Episode(
            key="episode:two",
            members=[Member(second.activity_id, "CME", "info")],
            severity="info",
        ),
    ]
    page = render_site(
        episodes,
        {first.activity_id: first, second.activity_id: second},
        tmp_path,
    ).read_text(encoding="utf-8")
    assert page.count("no WSA-Enlil run yet") == 2


def test_two_catalog_entries_for_one_shock_keep_only_the_severest_row(tmp_path: Path) -> None:
    arrival = _now() + dt.timedelta(hours=20)
    mild = EnlilRun(arrival_time=arrival, predicted_kp=3.0, is_earth_gb=True)
    fierce = EnlilRun(arrival_time=arrival, predicted_kp=7.0, is_earth_gb=True)
    one = _cme("2026-07-16T12:00:00-CME-001", has_analysis=True, enlil=mild)
    two = _cme("2026-07-16T12:00:00-CME-002", has_analysis=True, enlil=fierce, speed=900.0)
    low = Episode(
        key="episode:a", members=[Member(one.activity_id, "CME", "high")], severity="high"
    )
    high = Episode(
        key="episode:b", members=[Member(two.activity_id, "CME", "critical")], severity="critical"
    )
    page = render_site(
        [low, high], {one.activity_id: one, two.activity_id: two}, tmp_path
    ).read_text(encoding="utf-8")
    assert page.count(f'data-arrival="{arrival.isoformat()}"') == 1
    assert "severity-critical" in page
    assert "Predicted Kp <strong>7</strong>" in page


def test_duplicate_shock_keeps_strongest_forecast_and_critical_episode_style(
    tmp_path: Path,
) -> None:
    arrival = _now() + dt.timedelta(hours=20)
    stronger_forecast = _cme(
        "CME-KP6",
        has_analysis=True,
        enlil=EnlilRun(arrival, 6.0, True),
    )
    critical_context = _cme(
        "CME-KP5-CRITICAL",
        has_analysis=True,
        enlil=EnlilRun(arrival, 5.0, True),
    )
    episodes = [
        Episode(
            key="episode:high",
            members=[Member(stronger_forecast.activity_id, "CME", "high")],
            severity="high",
        ),
        Episode(
            key="episode:critical",
            members=[Member(critical_context.activity_id, "CME", "critical")],
            severity="critical",
        ),
    ]
    page = render_site(
        episodes,
        {
            stronger_forecast.activity_id: stronger_forecast,
            critical_context.activity_id: critical_context,
        },
        tmp_path,
    ).read_text(encoding="utf-8")
    assert page.count(f'data-arrival="{arrival.isoformat()}"') == 1
    assert "Predicted Kp <strong>6</strong>" in page
    assert "arrival-row severity-critical" in page


def test_linked_duplicate_cmes_render_one_activity_card(tmp_path: Path) -> None:
    arrival = _now() + dt.timedelta(hours=20)
    first = _cme(
        "CME-ACTIVITY-1",
        has_analysis=True,
        enlil=EnlilRun(arrival, 5.0, True),
    )
    second = _cme(
        "CME-ACTIVITY-2",
        has_analysis=True,
        enlil=EnlilRun(arrival, 6.0, True),
    )
    second.start_time = first.start_time
    page = _page_for([first, second], tmp_path, severity="high")
    assert page.count("activity-item activity-cme") == 1


def test_future_arrivals_are_sorted_soonest_first(tmp_path: Path) -> None:
    soon = _now() + dt.timedelta(hours=8)
    later = _now() + dt.timedelta(hours=36)
    first = _cme(
        "CME-LATER",
        has_analysis=True,
        enlil=EnlilRun(later, 5.0, True),
    )
    second = _cme(
        "CME-SOON",
        has_analysis=True,
        enlil=EnlilRun(soon, 6.0, True),
    )
    page = _page_for([first, second], tmp_path)
    outlook = page.split('<div class="arrivals-card">', 1)[1]
    assert outlook.index(soon.strftime("%Y-%m-%d %H:%M UTC")) < outlook.index(
        later.strftime("%Y-%m-%d %H:%M UTC")
    )


def test_recent_m_flare_appears_with_radio_context_and_source(tmp_path: Path) -> None:
    flare = Flare(
        flr_id="FLR-M3",
        peak_time=_now() - dt.timedelta(hours=4),
        class_type="M3.2",
        active_region=14493,
        link="https://example.test/donki-flare",
    )
    episode = Episode(
        key="episode:flare",
        members=[Member(flare.activity_id, "FLR", "high")],
        severity="high",
    )
    page = render_site([episode], {flare.activity_id: flare}, tmp_path).read_text(encoding="utf-8")
    assert "<strong>M3.2</strong> flare" in page
    assert "R1-R2" in page
    assert "Active region 14493" in page
    assert 'href="https://example.test/donki-flare"' in page


def test_partial_source_failure_preserves_known_arrival(tmp_path: Path) -> None:
    arrival = _now() + dt.timedelta(hours=18)
    cme = _cme(
        has_analysis=True,
        enlil=EnlilRun(arrival_time=arrival, predicted_kp=7.0, is_earth_gb=True),
    )
    episode = Episode(
        key="episode:partial",
        members=[Member(cme.activity_id, "CME", "critical")],
        severity="critical",
    )
    page = render_site([episode], {cme.activity_id: cme}, tmp_path, sources_ok=False).read_text(
        encoding="utf-8"
    )
    assert "Partial outlook" in page
    assert arrival.strftime("%Y-%m-%d %H:%M UTC") in page
    assert "Arrival outlook unavailable" not in page


def test_recent_storm_without_kp_is_pending_not_quiet(tmp_path: Path) -> None:
    storm = Storm(
        gst_id="GST-PENDING",
        start_time=_now() - dt.timedelta(hours=2),
        max_kp=None,
        link="https://example.test/storm-pending",
    )
    episode = Episode(
        key="episode:storm-pending",
        members=[Member(storm.activity_id, "GST", "info")],
        severity="info",
    )
    page = render_site([episode], {storm.activity_id: storm}, tmp_path).read_text(encoding="utf-8")
    assert "Kp pending" in page
    assert "Storm record awaiting Kp data" in page
    assert "No recent storm recorded" not in page


def test_known_storm_keeps_a_pending_kp_caveat(tmp_path: Path) -> None:
    known = Storm(
        gst_id="GST-KNOWN",
        start_time=_now() - dt.timedelta(hours=8),
        max_kp=5.0,
    )
    pending = Storm(
        gst_id="GST-PENDING",
        start_time=_now() - dt.timedelta(hours=2),
        max_kp=None,
    )
    episodes = [
        Episode(
            key=f"episode:{storm.activity_id}",
            members=[Member(storm.activity_id, "GST", "high")],
            severity="high",
        )
        for storm in (known, pending)
    ]
    page = render_site(
        episodes,
        {storm.activity_id: storm for storm in (known, pending)},
        tmp_path,
    ).read_text(encoding="utf-8")
    assert "Recent storm maximum measured" in page
    assert "maximum currently measured" in page
    assert "Maximum known Kp 5" in page
    assert "Another recent storm is awaiting Kp data" in page


def test_observed_storm_outranks_a_routine_pending_cme_in_the_hero(tmp_path: Path) -> None:
    cme = _cme(has_analysis=False)
    storm = Storm(
        gst_id="GST-KP7",
        start_time=_now() - dt.timedelta(hours=2),
        max_kp=7.0,
    )
    episodes = [
        Episode(
            key="episode:cme",
            members=[Member(cme.activity_id, "CME", "info")],
            severity="info",
        ),
        Episode(
            key="episode:storm",
            members=[Member(storm.activity_id, "GST", "critical")],
            severity="critical",
        ),
    ]
    page = render_site(
        episodes,
        {cme.activity_id: cme, storm.activity_id: storm},
        tmp_path,
    ).read_text(encoding="utf-8")
    hero = page.split('<section class="hero"', 1)[1].split("</section>", 1)[0]
    assert "Maximum Kp 7" in hero
    assert "CME forecast pending" not in hero
