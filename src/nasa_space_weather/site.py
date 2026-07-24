"""Build the static Space-Weather Watch dashboard.

Python owns every scientific classification and wording decision. The browser receives a
complete, useful document and adds only progressive presentation features such as local-time
labels and arrival countdowns.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from html import escape
from pathlib import Path
from typing import Any

from . import config, summary
from .episodes import Episode
from .models import CME, Flare, Storm
from .render import aurora_latitude, radio_blackout, satellite_note

_ASSET_SOURCE = Path(__file__).with_name("site_assets")
_ASSET_NAMES = ("site.css", "site.js")
_SEVERITY_RANK = {"info": 0, "high": 1, "critical": 2}
_SITE_URL = "https://ryastra.github.io/nasa-space-weather/"
_REPOSITORY_URL = "https://github.com/RYASTRA/nasa-space-weather"
_DONKI_URL = "https://ccmc.gsfc.nasa.gov/tools/DONKI/"

_AURORA_GUIDE = [
    (5, "~55°", "High latitudes", "Scotland, Scandinavia, Canada"),
    (6, "~50°", "Auroral zone expands", "Northern UK and northern US border states"),
    (7, "~45°", "Mid-latitudes", "Much of the northern US and central Europe"),
    (8, "~40°", "Well into mid-latitudes", "A rare, severe geomagnetic response"),
]


def _stamp(when: dt.datetime | None) -> str:
    return when.strftime("%Y-%m-%d %H:%M UTC") if when else "time unknown"


def _time_element(when: dt.datetime | None) -> str:
    if when is None:
        return '<span class="event-time">Time unknown</span>'
    return (
        f'<time class="event-time" datetime="{escape(when.isoformat())}" data-local-time>'
        f"{escape(_stamp(when))}</time>"
    )


def _source_link(event: Any, label: str = "NASA source") -> str:
    link = str(getattr(event, "link", "") or "")
    if not link:
        return ""
    return (
        f'<a class="source-link" href="{escape(link)}">'
        f'<span>{escape(label)}</span><span aria-hidden="true">↗</span></a>'
    )


def _arrival_groups(
    episodes: list[Episode], events: dict[str, Any], now: dt.datetime
) -> tuple[
    list[tuple[dt.datetime, Episode, CME]],
    list[tuple[dt.datetime, Episode, CME]],
    list[tuple[dt.datetime | None, Episode, CME]],
]:
    # pylint: disable=too-many-locals
    """Split CME rows into future forecasts, recent model times, and assessments."""
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    assessments: dict[str, tuple[Episode, CME]] = {}
    episode_by_arrival: dict[str, Episode] = {}

    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if not isinstance(event, CME):
                continue
            arrival = (
                event.enlil.arrival_time if event.has_analysis and event.enlil is not None else None
            )
            if arrival is not None:
                arrival_key = arrival.isoformat()
                previous_episode = episode_by_arrival.get(arrival_key)
                if previous_episode is None or _SEVERITY_RANK.get(
                    episode.severity, 0
                ) > _SEVERITY_RANK.get(previous_episode.severity, 0):
                    episode_by_arrival[arrival_key] = episode
                continue

            if event.start_time is not None and event.start_time < cutoff:
                continue
            # Linked catalog entries can describe the same eruption and forecast state.
            # Collapse those without hiding genuinely different assessments.
            state = _no_arrival_status(event)
            start_key = event.start_time.isoformat() if event.start_time is not None else "unknown"
            key = f"{episode.key}:{start_key}:{state}"
            previous = assessments.get(key)
            if previous is None or _SEVERITY_RANK.get(episode.severity, 0) > _SEVERITY_RANK.get(
                previous[0].severity, 0
            ):
                assessments[key] = (episode, event)

    selected_future, selected_recent = summary.arrival_buckets(
        summary.episode_events(episodes, events), now
    )

    def rows(selected: list[CME], *, reverse: bool) -> list[tuple[dt.datetime, Episode, CME]]:
        out: list[tuple[dt.datetime, Episode, CME]] = []
        for event in selected:
            arrival = event.enlil.arrival_time if event.enlil is not None else None
            episode = episode_by_arrival.get(arrival.isoformat()) if arrival is not None else None
            if arrival is not None and episode is not None:
                out.append((arrival, episode, event))
        return sorted(out, key=lambda row: row[0], reverse=reverse)

    future = rows(selected_future, reverse=False)
    recent = rows(selected_recent, reverse=True)
    pending = [(event.start_time, episode, event) for episode, event in assessments.values()]
    pending.sort(
        key=lambda row: row[0] or dt.datetime.min.replace(tzinfo=dt.UTC),
        reverse=True,
    )
    return future, recent, pending


def _no_arrival_status(cme: CME) -> str:
    """Explain each no-arrival state without letting missing data read as safety."""
    if not cme.has_analysis:
        return "<strong>arrival prediction not yet available</strong> (not yet analysed)"
    if cme.enlil is None:
        return "<strong>arrival prediction not yet available</strong> (no WSA-Enlil run yet)"
    if cme.enlil.is_earth_gb:
        return "<strong>Earth impact expected</strong> — shock arrival time not yet estimated"
    return "analysed: not currently predicted to reach Earth"


def _arrival_row(
    arrival: dt.datetime,
    episode: Episode,
    cme: CME,
    *,
    model_time_passed: bool,
) -> str:
    kp = cme.enlil.predicted_kp if cme.enlil is not None else None
    kp_html = ""
    if kp is not None:
        kp_html = (
            f'<span class="arrival-kp">Predicted Kp <strong>{kp:.0f}</strong></span>'
            f"<p>{escape(aurora_latitude(kp))}</p>"
        )
    speed = (
        f'<span class="arrival-detail">{cme.speed_kms:.0f} km/s at the Sun</span>'
        if cme.speed_kms is not None
        else ""
    )
    verb = "Forecast time" if model_time_passed else "Expected"
    return f"""
<article class="arrival-row severity-{escape(episode.severity)}"
         data-arrival="{escape(arrival.isoformat())}">
  <div class="arrival-row__marker" aria-hidden="true"></div>
  <div class="arrival-row__content">
    <div class="arrival-row__heading">
      <div>
        <span class="severity-label">{escape(episode.severity)}</span>
        <h4>{verb} {_time_element(arrival)}</h4>
      </div>
      <span class="countdown" data-countdown="{escape(arrival.isoformat())}">
        Arrival time shown in UTC
      </span>
    </div>
    <div class="arrival-meta">{speed}{kp_html}</div>
    {_source_link(cme, "Open CME record")}
  </div>
</article>"""


def _assessment_row(when: dt.datetime | None, episode: Episode, cme: CME) -> str:
    speed = f"<span>{cme.speed_kms:.0f} km/s</span>" if cme.speed_kms is not None else ""
    if not cme.has_analysis or cme.enlil is None:
        label = "Awaiting forecast"
        css_class = "pending"
    elif cme.enlil.is_earth_gb:
        label = "Impact · ETA pending"
        css_class = "impact"
    else:
        label = "Predicted miss"
        css_class = "miss"
    return f"""
<article class="assessment-row assessment-{css_class} severity-{escape(episode.severity)}">
  <div>
    <span class="assessment-label">{label}</span>
    <h4>CME {_time_element(when)}</h4>
    <p>{_no_arrival_status(cme)}</p>
  </div>
  <div class="assessment-meta">{speed}{_source_link(cme, "Open CME record")}</div>
</article>"""


def _arrival_section(
    title: str,
    description: str,
    rows: list[tuple[dt.datetime, Episode, CME]],
    *,
    model_time_passed: bool = False,
) -> str:
    if not rows:
        return ""
    rendered = "".join(
        _arrival_row(when, episode, cme, model_time_passed=model_time_passed)
        for when, episode, cme in rows
    )
    return f"""
<section class="arrival-group">
  <div class="arrival-group__heading">
    <h3>{escape(title)}</h3>
    <p>{escape(description)}</p>
  </div>
  <div class="arrival-list">{rendered}</div>
</section>"""


def _arrivals(
    episodes: list[Episode],
    events: dict[str, Any],
    now: dt.datetime,
    *,
    sources_ok: bool,
) -> str:
    future, recent, assessments = _arrival_groups(episodes, events, now)
    has_records = bool(future or recent or assessments)
    if not sources_ok and not has_records:
        return """
<div class="empty-state empty-state--warning">
  <strong>Arrival outlook unavailable</strong>
  <p>One or more DONKI feeds failed during this check. Quiet cannot be confirmed.</p>
</div>"""
    if not has_records:
        return """
<div class="empty-state">
  <span class="empty-state__icon" aria-hidden="true">◎</span>
  <strong>Nothing inbound.</strong>
  <p>No Earth arrival is currently forecast, and no recent CME is awaiting assessment.</p>
</div>"""

    sections = (
        [
            """
<div class="partial-data-note">
  <strong>Partial outlook</strong>
  <span>These records are available, but one or more DONKI feeds failed this check.</span>
</div>"""
        ]
        if not sources_ok
        else []
    )
    sections.extend(
        [
            _arrival_section(
                "Earth-arrival forecasts",
                "Future WSA-Enlil model times from the last hourly check, soonest first.",
                future,
            ),
            _arrival_section(
                "Recent modelled arrival times",
                f"WSA-Enlil forecast times that passed inside the last "
                f"{config.RELEVANCE_WINDOW_H} hours.",
                recent,
                model_time_passed=True,
            ),
        ]
    )
    if assessments:
        rendered = "".join(
            _assessment_row(when, episode, cme) for when, episode, cme in assessments
        )
        sections.append(
            f"""
<section class="arrival-group">
  <div class="arrival-group__heading">
    <h3>Recent CME assessments</h3>
    <p>Pending forecasts and analysed misses stay separate from Earth-arrival forecasts.</p>
  </div>
  <div class="assessment-list">{rendered}</div>
</section>"""
        )
    return "".join(sections)


def _conditions(evs: list[Any], now: dt.datetime, *, sources_ok: bool) -> str:
    storms = summary.recent_storms(evs, now)
    if not storms and not sources_ok:
        return """
<article class="condition-card condition-card--unknown">
  <p class="eyebrow">Geomagnetic activity · 72h</p>
  <div class="condition-value">Unknown</div>
  <h3>Conditions cannot be confirmed</h3>
  <p>At least one DONKI source was unavailable during this run.</p>
</article>"""

    if not storms:
        return f"""
<article class="condition-card condition-card--quiet">
  <p class="eyebrow">Geomagnetic activity · {config.RELEVANCE_WINDOW_H}h</p>
  <div class="condition-value condition-value--small">No storm</div>
  <h3>No recent storm recorded</h3>
  <p>DONKI recorded no geomagnetic storm starting inside the
     {config.RELEVANCE_WINDOW_H}-hour relevance window.</p>
  <div class="condition-note">
    <span aria-hidden="true">◎</span>
    This is an event-history check, not a live Kp measurement or local aurora forecast.
  </div>
</article>"""

    known_storms = [storm for storm in storms if storm.max_kp is not None]
    pending_storms = [storm for storm in storms if storm.max_kp is None]
    worst = (
        max(known_storms, key=lambda storm: storm.max_kp or 0)
        if known_storms
        else max(
            storms, key=lambda storm: storm.start_time or dt.datetime.min.replace(tzinfo=dt.UTC)
        )
    )
    caveat = (
        """
  <div class="condition-note condition-note--warning">
    <span aria-hidden="true">!</span>
    Other DONKI data is incomplete for this check; this is the available storm record.
  </div>"""
        if not sources_ok
        else ""
    )
    if worst.max_kp is None:
        return f"""
<article class="condition-card condition-card--pending">
  <p class="eyebrow">Recent geomagnetic storm</p>
  <div class="condition-value condition-value--small">Kp pending</div>
  <h3>Storm record awaiting Kp data</h3>
  <p>DONKI published a storm beginning {_time_element(worst.start_time)}, but its Kp
     series is not available yet.</p>
  <div class="condition-note">
    <span aria-hidden="true">…</span>
    Impact and aurora context will appear when the measured Kp series arrives.
  </div>
  {caveat}
  {_source_link(worst, "Open storm record")}
</article>"""

    kp = worst.max_kp
    pending_caveat = (
        """
  <div class="condition-note condition-note--warning">
    <span aria-hidden="true">…</span>
    Another recent storm is awaiting Kp data; this is the maximum currently measured.
  </div>"""
        if pending_storms
        else ""
    )
    return f"""
<article class="condition-card condition-card--storm">
  <p class="eyebrow">Recent storm maximum measured</p>
  <div class="condition-value">Kp {kp:.0f}</div>
  <h3>{escape(aurora_latitude(kp))}</h3>
  <p>Storm record began {_time_element(worst.start_time)}. Kp is the maximum in that
     DONKI record, not a live local reading.</p>
  <div class="condition-note">
    <span aria-hidden="true">△</span>
    {escape(satellite_note(kp))}
  </div>
  {pending_caveat}
  {caveat}
  {_source_link(worst, "Open storm record")}
</article>"""


def _activity_items(
    evs: list[Any],
    activity_cmes: list[CME],
    now: dt.datetime,
) -> list[tuple[dt.datetime | None, str]]:
    week_ago = now - dt.timedelta(days=7)
    major_flare_ids = {flare.activity_id for flare in summary.recent_major_flares(evs, now)}
    activity_cme_ids = {cme.activity_id for cme in activity_cmes}
    rows: list[tuple[dt.datetime | None, str]] = []
    for event in evs:
        if isinstance(event, Flare) and event.activity_id in major_flare_ids:
            region = (
                f"Active region {event.active_region}" if event.active_region else "Solar region"
            )
            rows.append(
                (
                    event.peak_time,
                    f"""
<article class="activity-item activity-flare">
  <div class="activity-icon" aria-hidden="true">✦</div>
  <div class="activity-body">
    <span class="activity-type">Solar flare</span>
    <h3><strong>{escape(event.class_type)}</strong> flare · {escape(region)}</h3>
    <p>{escape(radio_blackout(event.class_type))}</p>
    <div class="activity-footer">{_time_element(event.peak_time)}
      {_source_link(event)}</div>
  </div>
</article>""",
                )
            )
        elif isinstance(event, CME) and event.activity_id in activity_cme_ids:
            speed = f" · {event.speed_kms:.0f} km/s" if event.speed_kms is not None else ""
            arrival = event.enlil.arrival_time if event.enlil is not None else None
            outlook = (
                f"Modelled Earth arrival {_stamp(arrival)}."
                if arrival is not None
                else "Earth impact is flagged; arrival time is not yet estimated."
            )
            rows.append(
                (
                    event.start_time,
                    f"""
<article class="activity-item activity-cme">
  <div class="activity-icon" aria-hidden="true">◌</div>
  <div class="activity-body">
    <span class="activity-type">Coronal mass ejection</span>
    <h3>Earth-relevant CME{escape(speed)}</h3>
    <p>{escape(outlook)}</p>
    <div class="activity-footer">{_time_element(event.start_time)}
      {_source_link(event)}</div>
  </div>
</article>""",
                )
            )
        elif (
            isinstance(event, Storm)
            and event.start_time is not None
            and event.start_time >= week_ago
        ):
            storm_heading = (
                f"Storm record · maximum Kp {event.max_kp:.0f}"
                if event.max_kp is not None
                else "Storm record · Kp pending"
            )
            storm_context = (
                aurora_latitude(event.max_kp)
                if event.max_kp is not None
                else "Kp series not available yet; impact context is pending."
            )
            rows.append(
                (
                    event.start_time,
                    f"""
<article class="activity-item activity-storm">
  <div class="activity-icon" aria-hidden="true">≋</div>
  <div class="activity-body">
    <span class="activity-type">Geomagnetic storm</span>
    <h3>{escape(storm_heading)}</h3>
    <p>{escape(storm_context)}</p>
    <div class="activity-footer">{_time_element(event.start_time)}
      {_source_link(event)}</div>
  </div>
</article>""",
                )
            )
    return sorted(
        rows,
        key=lambda row: row[0] or dt.datetime.min.replace(tzinfo=dt.UTC),
        reverse=True,
    )


def _activity(
    evs: list[Any],
    activity_cmes: list[CME],
    now: dt.datetime,
    *,
    sources_ok: bool,
) -> str:
    rows = _activity_items(evs, activity_cmes, now)
    if not sources_ok and not rows:
        return """
<div class="empty-state empty-state--warning">
  <strong>Recent activity is incomplete</strong>
  <p>The feed needs to recover before this seven-day view can be trusted.</p>
</div>"""
    if not rows:
        return """
<div class="empty-state">
  <span class="empty-state__icon" aria-hidden="true">✦</span>
  <strong>No high-signal activity in seven days</strong>
  <p>No M/X flare, Earth-relevant CME, or geomagnetic storm was recorded.</p>
</div>"""
    notice = (
        """
<div class="partial-data-note">
  <strong>Partial activity record</strong>
  <span>Available events are shown; one or more DONKI feeds failed this check.</span>
</div>"""
        if not sources_ok
        else ""
    )
    return notice + "".join(markup for _, markup in rows[:8])


def _hero_metrics(
    episodes: list[Episode], events: dict[str, Any], now: dt.datetime, *, sources_ok: bool
) -> str:
    evs = summary.episode_events(episodes, events)
    future, recent = summary.arrival_buckets(evs, now)
    flares = len(summary.recent_major_flares(evs, now))

    def count_value(count: int) -> str:
        if sources_ok:
            return str(count)
        return f"≥{count}" if count else "Unknown"

    metrics = (
        (
            "Last check",
            "Healthy" if sources_ok else "Degraded",
            "metric-health" if sources_ok else "metric-health metric-health--degraded",
            "health",
        ),
        ("Future forecasts", count_value(len(future)), "", "future"),
        (
            f"Recent model times · {config.RELEVANCE_WINDOW_H}h",
            count_value(len(recent)),
            "",
            "recent",
        ),
        ("M/X flares · 7d", count_value(flares), "", "flares"),
    )
    return "".join(
        f"""
<div class="metric {css_class}" data-metric="{metric_key}">
  <dt>{escape(label)}</dt>
  <dd>{escape(value)}</dd>
</div>"""
        for label, value, css_class, metric_key in metrics
    )


def _hero_signal(
    episodes: list[Episode], events: dict[str, Any], now: dt.datetime, *, sources_ok: bool
) -> str:
    # A priority-ordered status renderer is clearer as explicit early returns for each
    # mutually exclusive state than as one deeply nested template expression.
    # pylint: disable=too-many-locals,too-many-return-statements
    evs = summary.episode_events(episodes, events)
    future, recent, assessments = _arrival_groups(episodes, events, now)
    impact_pending = next(
        (cme for _, _, cme in assessments if cme.enlil is not None and cme.enlil.is_earth_gb),
        None,
    )
    if impact_pending is not None:
        eruption = (
            f"a CME from {_time_element(impact_pending.start_time)}"
            if impact_pending.start_time is not None
            else "a CME with an unknown eruption time"
        )
        return f"""
<div class="hero-signal hero-signal--warning">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Earth-impact outlook</small><strong>Earth impact expected · ETA pending</strong>
    <p>WSA-Enlil flags {eruption}; the modelled arrival time is unavailable.</p>
  </div>
</div>"""

    if future:
        when, _, cme = future[0]
        kp = cme.enlil.predicted_kp if cme.enlil is not None else None
        detail = f"Predicted Kp {kp:.0f}" if kp is not None else "Earth arrival modelled"
        return f"""
<div class="hero-signal hero-signal--arrival"
     data-hero-arrival="{escape(when.isoformat())}">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Next modelled Earth arrival · last check</small>
    <strong>{_time_element(when)}</strong>
    <p>{escape(detail)}</p></div>
</div>"""

    storms = summary.recent_storms(evs, now)
    if storms:
        known_storms = [storm for storm in storms if storm.max_kp is not None]
        pending_storms = [storm for storm in storms if storm.max_kp is None]
        worst = (
            max(known_storms, key=lambda storm: storm.max_kp or 0)
            if known_storms
            else max(
                storms,
                key=lambda storm: storm.start_time or dt.datetime.min.replace(tzinfo=dt.UTC),
            )
        )
        storm_value = (
            f"Maximum {'known ' if pending_storms else ''}Kp {worst.max_kp:.0f}"
            if worst.max_kp is not None
            else "Kp series pending"
        )
        pending_context = (
            " Another recent storm is awaiting Kp data." if known_storms and pending_storms else ""
        )
        return f"""
<div class="hero-signal">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Recent geomagnetic storm</small><strong>{storm_value}</strong>
    <p>Started {escape(_stamp(worst.start_time))}.{pending_context}</p></div>
</div>"""

    if recent:
        when, _, cme = recent[0]
        kp = cme.enlil.predicted_kp if cme.enlil is not None else None
        detail = f"Modelled Kp {kp:.0f}" if kp is not None else "Forecast time passed"
        return f"""
<div class="hero-signal">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Latest modelled arrival time</small><strong>{_time_element(when)}</strong>
    <p>{escape(detail)}</p></div>
</div>"""

    forecast_pending = next(
        (cme for _, _, cme in assessments if not cme.has_analysis or cme.enlil is None),
        None,
    )
    if forecast_pending is not None:
        eruption = (
            f"erupted {_time_element(forecast_pending.start_time)}"
            if forecast_pending.start_time is not None
            else "has an unknown eruption time"
        )
        return f"""
<div class="hero-signal hero-signal--pending">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Earth-impact outlook</small><strong>CME forecast pending</strong>
    <p>A CME {eruption} and is awaiting analysis.</p>
  </div>
</div>"""

    if not sources_ok:
        return """
<div class="hero-signal hero-signal--warning">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Earth-impact outlook</small><strong>Feed degraded</strong>
    <p>Quiet cannot be confirmed until all DONKI sources recover.</p></div>
</div>"""

    return """
<div class="hero-signal hero-signal--quiet">
  <span class="signal-pulse" aria-hidden="true"></span>
  <div><small>Earth-impact outlook</small><strong>No Earth arrival forecast</strong>
    <p>The latest complete DONKI check found no modelled Earth arrival.</p></div>
</div>"""


def _aurora_rows() -> str:
    return "".join(
        f"""
<tr>
  <th scope="row"><span class="kp-dot kp-{kp}"></span>Kp {kp}</th>
  <td><strong>{latitude}</strong><span>{escape(label)}</span></td>
  <td>{escape(context)}</td>
</tr>"""
        for kp, latitude, label, context in _AURORA_GUIDE
    )


def _feed_warning(sources_ok: bool) -> str:
    if sources_ok:
        return ""
    return """
<aside class="feed-warning" aria-labelledby="feed-warning-title">
  <span class="feed-warning__icon" aria-hidden="true">!</span>
  <div>
    <strong id="feed-warning-title">DONKI data is incomplete for this check</strong>
    <p>One or more upstream feeds failed. Empty results below are marked unknown instead of
       being presented as safe conditions. The watcher will retry on its next hourly run.</p>
  </div>
</aside>"""


def _stale_warning() -> str:
    return f"""
<aside class="feed-warning stale-warning" data-stale-warning
       aria-labelledby="stale-warning-title" hidden>
  <span class="feed-warning__icon" aria-hidden="true">!</span>
  <div>
    <strong id="stale-warning-title">This page is older than expected</strong>
    <p>No successful publish has reached this page within
       {config.SITE_FRESH_FOR_HOURS} hours. Treat every outlook as stale until the next run.</p>
  </div>
</aside>"""


def _page(
    episodes: list[Episode],
    events: dict[str, Any],
    now: dt.datetime,
    *,
    sources_ok: bool,
) -> str:
    evs = summary.episode_events(episodes, events)
    generated = _stamp(now)
    health_label = "Last check healthy" if sources_ok else "Last check degraded"
    health_class = "healthy" if sources_ok else "degraded"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="NASA DONKI space-weather events translated into a calm,
readable Earth-impact outlook for aurora, radio, and satellite operators.">
<meta name="theme-color" content="#050812">
<meta property="og:type" content="website">
<meta property="og:title" content="Space-Weather Watch">
<meta property="og:description" content="The Sun, made legible—an hourly,
deterministic Earth-impact outlook from NASA DONKI.">
<link rel="canonical" href="{_SITE_URL}">
<title>Space-Weather Watch</title>
<link rel="stylesheet" href="assets/site.css">
<script src="assets/site.js" defer></script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>

<header class="site-header">
  <div class="site-header__inner">
    <a class="brand" href="./" aria-label="Space-Weather Watch home">
      <span>Space Weather <strong>Watch</strong></span>
    </a>
    <nav class="site-nav" aria-label="Primary navigation">
      <a href="#outlook">Outlook</a>
      <a href="#activity">Activity</a>
      <a href="#impact-guide">Impact guide</a>
      <a href="#method">Method</a>
    </nav>
    <span class="feed-chip feed-chip--{health_class}" data-feed-health
          data-generated="{escape(now.isoformat())}"
          data-fresh-hours="{config.SITE_FRESH_FOR_HOURS}">
      <span aria-hidden="true"></span><span class="feed-chip__label">{health_label}</span>
    </span>
  </div>
</header>

<main id="main">
  <section class="hero" aria-labelledby="hero-title">
    <div class="hero__content">
      <p class="eyebrow">NASA DONKI · scheduled hourly</p>
      <h1 id="hero-title">The Sun,<br><em>made legible.</em></h1>
      <p class="hero__lede">Earth-directed eruptions, geomagnetic storms, and aurora
         potential—translated into a calm, readable signal.</p>
      <div class="hero__actions">
        <a class="button button--primary" href="#outlook">See Earth outlook</a>
        <a class="button" href="{_REPOSITORY_URL}/issues">View alert issues</a>
      </div>
      <p class="last-checked">Last checked:
        <time datetime="{escape(now.isoformat())}" data-local-time>{escape(generated)}</time>
      </p>
      {_hero_signal(episodes, events, now, sources_ok=sources_ok)}
    </div>

    <div class="solar-visual" aria-hidden="true">
      <div class="solar-wind solar-wind--one"></div>
      <div class="solar-wind solar-wind--two"></div>
      <div class="solar-wind solar-wind--three"></div>
      <div class="sun">
        <span class="sun-spot sun-spot--one"></span>
        <span class="sun-spot sun-spot--two"></span>
        <span class="sun-flare"></span>
      </div>
      <div class="earth"><span></span></div>
      <div class="aurora aurora--one"></div>
      <div class="aurora aurora--two"></div>
    </div>

    <dl class="metrics-grid">
      {_hero_metrics(episodes, events, now, sources_ok=sources_ok)}
    </dl>
  </section>

  {_feed_warning(sources_ok)}
  {_stale_warning()}

  <section class="outlook-section" id="outlook" aria-labelledby="outlook-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Earth-impact outlook</p>
        <h2 id="outlook-title">What is happening now</h2>
      </div>
      <p>Observed storms and modelled CME arrival times are deliberately kept distinct.</p>
    </div>
    <div class="outlook-grid">
      {_conditions(evs, now, sources_ok=sources_ok)}
      <div class="arrivals-card">
        <div class="card-heading">
          <div><p class="eyebrow">WSA-Enlil forecast</p><h2>CME outlook</h2></div>
          <span class="window-label">{config.RELEVANCE_WINDOW_H}h relevance window</span>
        </div>
        {_arrivals(episodes, events, now, sources_ok=sources_ok)}
      </div>
    </div>
  </section>

  <section class="signal-section" aria-labelledby="signal-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">One connected story</p>
        <h2 id="signal-title">From solar eruption to Earth</h2>
      </div>
      <p>Events are connected only when NASA's own linked-event graph connects them.</p>
    </div>
    <ol class="signal-chain">
      <li>
        <span class="signal-chain__number">01</span>
        <span class="signal-chain__icon" aria-hidden="true">✦</span>
        <h3>Flare</h3>
        <p>X-ray radiation reaches Earth first. M and X classes can disrupt HF radio on the
           daylit side.</p>
      </li>
      <li>
        <span class="signal-chain__number">02</span>
        <span class="signal-chain__icon" aria-hidden="true">◌</span>
        <h3>CME</h3>
        <p>A cloud of solar plasma may follow. WSA-Enlil models whether and when its shock
           reaches Earth.</p>
      </li>
      <li>
        <span class="signal-chain__number">03</span>
        <span class="signal-chain__icon" aria-hidden="true">≋</span>
        <h3>Storm</h3>
        <p>DONKI records the geomagnetic response. Kp supplies the shared context for aurora
           and spacecraft effects.</p>
      </li>
    </ol>
  </section>

  <section class="activity-section" id="activity" aria-labelledby="activity-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Seven-day signal</p>
        <h2 id="activity-title">Recent solar activity</h2>
      </div>
      <p>High-signal events only: M/X flares, Earth-relevant CMEs, and geomagnetic storms.</p>
    </div>
    <div class="activity-list">
      {
        _activity(
            evs,
            summary.activity_cmes(episodes, events, now),
            now,
            sources_ok=sources_ok,
        )
    }
    </div>
  </section>

  <section class="impact-section" id="impact-guide" aria-labelledby="impact-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">What it means for you</p>
        <h2 id="impact-title">Turn a signal into context</h2>
      </div>
      <p>Broad guidance, not a local sky forecast or an operational warning service.</p>
    </div>

    <div class="audience-grid">
      <article class="audience-card audience-card--aurora">
        <span class="audience-card__icon" aria-hidden="true">⌁</span>
        <p class="eyebrow">Aurora chasers</p>
        <h3>Kp suggests latitude—not clear skies</h3>
        <p>Higher Kp makes aurora plausible farther from the poles. Darkness, cloud, light
           pollution, and the storm's timing still decide what you see.</p>
      </article>
      <article class="audience-card audience-card--radio">
        <span class="audience-card__icon" aria-hidden="true">⌁</span>
        <p class="eyebrow">Radio operators</p>
        <h3>Flare class frames HF impact</h3>
        <p>M-class flares map to minor-to-moderate R1–R2 degradation. X-class events can
           produce R3+ blackouts on Earth's daylit side.</p>
      </article>
      <article class="audience-card audience-card--satellite">
        <span class="audience-card__icon" aria-hidden="true">△</span>
        <p class="eyebrow">Satellite operators</p>
        <h3>Storm strength frames risk</h3>
        <p>At Kp 5, mild drag and charging effects become plausible. At Kp 7+, elevated LEO
           drag and surface-charging risk merit attention.</p>
      </article>
    </div>

    <div class="aurora-guide">
      <div class="aurora-guide__intro">
        <p class="eyebrow">Northern Hemisphere guide</p>
        <h3>How far south could aurora reach?</h3>
        <p>Approximate geomagnetic latitude bands used throughout this watcher. Geographic
           latitude differs, and visibility is never guaranteed.</p>
      </div>
      <div class="table-scroll">
        <table>
          <caption class="visually-hidden">Kp index and approximate aurora latitude guide</caption>
          <thead><tr><th scope="col">Index</th><th scope="col">Latitude</th>
            <th scope="col">Plain-language context</th></tr></thead>
          <tbody>{_aurora_rows()}</tbody>
        </table>
      </div>
    </div>
  </section>

  <section class="method-section" id="method" aria-labelledby="method-title">
    <div class="method-copy">
      <p class="eyebrow">The honesty layer</p>
      <h2 id="method-title">Quiet by design.<br>Explicit about uncertainty.</h2>
      <p>Space-Weather Watch is a deterministic translation layer over NASA DONKI—not a
         second forecast model. It reports material changes, keeps missing analysis visible,
         and never lets an unavailable source masquerade as a quiet Sun.</p>
      <div class="method-actions">
        <a class="button button--primary" href="status.json">Open machine-readable status</a>
        <a class="button" href="{_REPOSITORY_URL}">Inspect the source</a>
      </div>
    </div>
    <ol class="method-steps">
      <li><span>01</span><div><strong>Fetch</strong>
        <p>Solar flares, CMEs, WSA-Enlil analyses, and storms from NASA DONKI.</p></div></li>
      <li><span>02</span><div><strong>Connect</strong>
        <p>Group events with NASA's linked-event graph; never invent causal links.</p></div></li>
      <li><span>03</span><div><strong>Detect</strong>
        <p>Compare versioned snapshots and suppress routine noise below material thresholds.</p>
      </div></li>
      <li><span>04</span><div><strong>Publish</strong>
        <p>Update idempotent GitHub Issues and this static page. No server or database.</p>
      </div></li>
    </ol>
  </section>
</main>

<footer class="site-footer">
  <div class="site-footer__inner">
    <div>
      <a class="brand brand--footer" href="./"><span>Space Weather <strong>Watch</strong></span></a>
      <p>Independent, deterministic, and built from NASA DONKI data. Not affiliated with or
         endorsed by NASA.</p>
    </div>
    <nav aria-label="Footer navigation">
      <a href="{_DONKI_URL}">NASA DONKI</a>
      <a href="status.json">Status JSON</a>
      <a href="{_REPOSITORY_URL}/issues">Alert issues</a>
      <a href="{_REPOSITORY_URL}">Source on GitHub</a>
    </nav>
    <p class="footer-meta">Generated {_time_element(now)} · no LLM in the alert path</p>
  </div>
</footer>
</body>
</html>
"""


def _copy_assets(out_dir: Path) -> None:
    target = out_dir / "assets"
    target.mkdir(exist_ok=True)
    for name in _ASSET_NAMES:
        shutil.copyfile(_ASSET_SOURCE / name, target / name)


def render_site(
    episodes: list[Episode],
    events: dict[str, Any],
    out_dir: Path,
    *,
    sources_ok: bool = True,
) -> Path:
    """Write the dashboard and status.json into ``out_dir``, returning the HTML path."""
    # Imported here so status.py can reuse site semantics without an import cycle.
    from . import status  # pylint: disable=import-outside-toplevel,cyclic-import

    out_dir.mkdir(parents=True, exist_ok=True)
    _copy_assets(out_dir)
    now = dt.datetime.now(dt.UTC)
    status_doc = status.build(episodes, events, now, sources_ok=sources_ok)
    (out_dir / "status.json").write_text(
        json.dumps(status_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path = out_dir / "index.html"
    path.write_text(_page(episodes, events, now, sources_ok=sources_ok), encoding="utf-8")
    return path
