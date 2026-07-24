"""Observatory status contract (schema 1) for this site.

Emits the small, stable status.json the NASA Observatory reads from every
fleet site's root. The contract is specified in the nasa-observatory
repo: docs/superpowers/specs/2026-07-22-nasa-observatory-design.md

The tile must retell the page, not reinterpret it: recent-storm, relevance
window, and Earth-directed-CME semantics are the ones site.py already uses.
Bounds: headline <= 120 chars, <= 5 items, item text <= 140 chars.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import config, summary
from .episodes import Episode
from .models import CME, Flare, Storm
from .render import aurora_latitude

_SITE_URL = "https://ryastra.github.io/nasa-space-weather/"


def _arrival_timeline(
    arrivals: list[CME], now: dt.datetime
) -> tuple[list[tuple[dt.datetime, dict]], list[tuple[dt.datetime, dict]]]:
    """Separate future model forecasts from recently passed model times."""
    future: list[tuple[dt.datetime, dict]] = []
    recent: list[tuple[dt.datetime, dict]] = []
    for cme in arrivals:
        if cme.enlil is None or cme.enlil.arrival_time is None:
            continue  # summary.arrival_buckets guarantees this; keeps narrowing local
        arrival = cme.enlil.arrival_time
        kp = cme.enlil.predicted_kp
        # The consumer renders when_utc beside the text, so the text names the
        # forecast's status without repeating its timestamp.
        arrival_text = (
            "CME arrival forecast" if arrival >= now else "Recent modelled CME arrival time"
        )
        kp_text = f" — Kp {kp:.0f}, {aurora_latitude(kp)}" if kp is not None else ""
        target = future if arrival >= now else recent
        target.append((arrival, {"text": f"{arrival_text}{kp_text}", "url": cme.link}))
    future.sort(key=lambda pair: pair[0])
    recent.sort(key=lambda pair: pair[0], reverse=True)
    return future, recent


def _timeline(
    flares: list[Flare],
    storms: list[Storm],
    arrivals: list[CME],
    pending_impacts: list[CME],
    *,
    now: dt.datetime,
) -> list[tuple[dt.datetime | None, dict]]:
    """Put nearest future forecasts first, followed by newest recent observations."""
    pending_items: list[tuple[dt.datetime | None, dict]] = [
        (
            cme.start_time,
            {
                "text": "Earth impact expected — CME arrival time pending",
                "url": cme.link,
            },
        )
        for cme in pending_impacts
    ]
    pending_items.sort(
        key=lambda pair: pair[0] or dt.datetime.min.replace(tzinfo=dt.UTC),
        reverse=True,
    )
    recent_items: list[tuple[dt.datetime, dict]] = []
    for flare in flares:
        if flare.peak_time is not None:
            region = f" — AR{flare.active_region}" if flare.active_region else ""
            recent_items.append(
                (
                    flare.peak_time,
                    {"text": f"{flare.class_type} flare{region}", "url": flare.link},
                )
            )
    for storm in storms:
        start = storm.start_time
        if start is not None:  # guaranteed by the filter above; keeps the narrowing local
            kp_text = f"max Kp {storm.max_kp:.0f}" if storm.max_kp is not None else "Kp pending"
            recent_items.append(
                (
                    start,
                    {"text": f"Geomagnetic storm — {kp_text}", "url": storm.link},
                )
            )
    future_items, recent_arrivals = _arrival_timeline(arrivals, now)
    recent_items.extend(recent_arrivals)
    recent_items.sort(key=lambda pair: pair[0], reverse=True)
    return [*pending_items, *future_items, *recent_items]


def _metric_value(count: int, *, sources_ok: bool) -> str:
    """Report exact healthy counts and conservative lower bounds for partial data."""
    if sources_ok:
        return str(count)
    return f"≥{count}" if count else "Unknown"


def _status_item(when: dt.datetime | None, item: dict) -> dict:
    """Serialize a timeline row, omitting the contract's optional time when unknown."""
    out = {"text": item["text"][:140], "url": item["url"]}
    if when is not None:
        out["when_utc"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def _headline(
    storms: list[Storm],
    pending_impacts: list[CME],
    future_arrivals: list[CME],
    *,
    sources_ok: bool,
) -> str:
    """Choose the tile's highest-signal, uncertainty-aware headline."""
    known_storms = [storm for storm in storms if storm.max_kp is not None]
    pending_storms = [storm for storm in storms if storm.max_kp is None]
    if pending_impacts:
        headline = "Earth impact expected — CME arrival time pending"
    elif future_arrivals:
        next_arrival = min(
            future_arrivals,
            key=lambda cme: (
                cme.enlil.arrival_time
                if cme.enlil is not None and cme.enlil.arrival_time is not None
                else dt.datetime.max.replace(tzinfo=dt.UTC)
            ),
        )
        kp = next_arrival.enlil.predicted_kp if next_arrival.enlil is not None else None
        kp_note = f" — predicted Kp {kp:.0f}" if kp is not None else ""
        headline = f"Earth-arrival forecast active{kp_note}"
    elif known_storms:
        worst = max(known_storms, key=lambda storm: storm.max_kp or 0)
        pending_note = "; another storm has Kp pending" if pending_storms else ""
        qualifier = "known " if pending_storms else ""
        headline = f"Recent geomagnetic storm — max {qualifier}Kp {worst.max_kp:.0f}{pending_note}"
    elif storms:
        headline = "Recent geomagnetic storm — Kp pending"
    elif not sources_ok:
        return "DONKI data incomplete"
    else:
        return "No recent geomagnetic storms"
    return f"{headline} · data incomplete" if not sources_ok else headline


def _metrics(
    big_flares: list[Flare],
    future_arrivals: list[CME],
    recent_arrivals: list[CME],
    pending_impacts: list[CME],
    *,
    sources_ok: bool,
) -> list[dict[str, str]]:
    """Build exact healthy metrics or conservative partial-data values."""
    return [
        {
            "label": "M+X flares · 7d",
            "value": _metric_value(len(big_flares), sources_ok=sources_ok),
        },
        {
            "label": "Future CME arrival forecasts",
            "value": _metric_value(len(future_arrivals), sources_ok=sources_ok),
        },
        {
            "label": f"Recent CME model times · {config.RELEVANCE_WINDOW_H}h",
            "value": _metric_value(len(recent_arrivals), sources_ok=sources_ok),
        },
        {
            "label": "Earth impacts · ETA pending",
            "value": _metric_value(len(pending_impacts), sources_ok=sources_ok),
        },
    ]


def build(
    episodes: list[Episode],
    events: dict[str, Any],
    now: dt.datetime,
    *,
    sources_ok: bool,
) -> dict:
    """The status.json document, from the same inputs render_site receives."""
    evs = summary.episode_events(episodes, events)
    storms = summary.recent_storms(evs, now)
    pending_impacts = summary.pending_earth_impacts(episodes, events, now)
    big_flares = summary.recent_major_flares(evs, now)
    future_arrivals, recent_arrivals = summary.arrival_buckets(evs, now)
    arrivals = [*future_arrivals, *recent_arrivals]

    items = _timeline(big_flares, storms, arrivals, pending_impacts, now=now)

    return {
        "schema": 1,
        "project": "nasa-space-weather",
        "title": "Space-Weather Watch",
        "site": _SITE_URL,
        "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fresh_for_hours": config.SITE_FRESH_FOR_HOURS,
        "ok": sources_ok,
        "headline": _headline(
            storms,
            pending_impacts,
            future_arrivals,
            sources_ok=sources_ok,
        )[:120],
        "metrics": _metrics(
            big_flares,
            future_arrivals,
            recent_arrivals,
            pending_impacts,
            sources_ok=sources_ok,
        ),
        "items": [_status_item(when, item) for when, item in items[:5]],
    }
