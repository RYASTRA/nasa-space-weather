"""Observatory status contract (schema 1) for this site.

Emits the small, stable status.json the NASA Observatory reads from every
fleet site's root. Contract spec:
https://github.com/RYASTRA/nasa-observatory/blob/main/docs/superpowers/specs/2026-07-22-nasa-observatory-design.md

The tile must retell the page, not reinterpret it: active-storm, relevance
window, and Earth-directed-CME semantics are the ones site.py already uses.
Bounds: headline <= 120 chars, <= 5 items, item text <= 140 chars.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import config
from .episodes import Episode
from .models import CME, Flare, Storm
from .render import aurora_latitude

_SITE_URL = "https://ryastra.github.io/nasa-space-weather/"


def _episode_events(episodes: list[Episode], events: dict[str, Any]) -> list[Any]:
    seen: dict[str, Any] = {}
    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if event is not None:
                seen.setdefault(member.activity_id, event)
    return list(seen.values())


def _pending_arrivals(evs: list[Any], now: dt.datetime) -> list[CME]:
    """Earth-relevant CMEs, one per predicted arrival moment (one shock, one row)."""
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    by_arrival: dict[str, CME] = {}
    for event in evs:
        if not isinstance(event, CME) or not event.has_analysis or event.enlil is None:
            continue
        arrival = event.enlil.arrival_time
        if arrival is None or arrival < cutoff:
            continue
        by_arrival.setdefault(arrival.isoformat(), event)
    return list(by_arrival.values())


def build(
    episodes: list[Episode],
    events: dict[str, Any],
    now: dt.datetime,
    *,
    sources_ok: bool,
) -> dict:
    """The status.json document, from the same inputs render_site receives."""
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    evs = _episode_events(episodes, events)

    storms = [
        s
        for s in evs
        if isinstance(s, Storm)
        and s.max_kp is not None
        and s.start_time is not None
        and s.start_time >= cutoff
    ]
    if storms:
        worst = max(storms, key=lambda s: s.max_kp or 0)
        headline = f"Geomagnetic storm — Kp {worst.max_kp:.0f}"
    else:
        headline = "Geomagnetically quiet"

    week_ago = now - dt.timedelta(days=7)
    big_flares = [
        f
        for f in evs
        if isinstance(f, Flare)
        and f.peak_time is not None
        and f.peak_time >= week_ago
        and f.class_type[:1] in ("M", "X")
    ]
    arrivals = _pending_arrivals(evs, now)

    items: list[tuple[dt.datetime, dict]] = []
    for event in evs:
        if isinstance(event, Flare) and event.peak_time is not None and event.peak_time >= week_ago:
            region = f" — AR{event.active_region}" if event.active_region else ""
            items.append(
                (event.peak_time, {"text": f"{event.class_type} flare{region}", "url": event.link})
            )
    for storm in storms:
        start = storm.start_time
        if start is not None:  # guaranteed by the filter above; keeps the narrowing local
            items.append(
                (
                    start,
                    {"text": f"Geomagnetic storm — max Kp {storm.max_kp:.0f}", "url": storm.link},
                )
            )
    for cme in arrivals:
        if cme.enlil is None or cme.enlil.arrival_time is None:
            continue  # _pending_arrivals guarantees otherwise; keeps the narrowing local
        arrival = cme.enlil.arrival_time
        kp = cme.enlil.predicted_kp
        verb = "expected" if arrival >= now else "arrived"
        kp_text = f" — Kp {kp:.0f}, {aurora_latitude(kp)}" if kp is not None else ""
        items.append(
            (
                arrival,
                {
                    "text": f"CME arrival {verb} {arrival:%b %-d %H:%M} UTC{kp_text}",
                    "url": cme.link,
                },
            )
        )
    items.sort(key=lambda pair: pair[0], reverse=True)

    return {
        "schema": 1,
        "project": "nasa-space-weather",
        "title": "Space-Weather Watch",
        "site": _SITE_URL,
        "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fresh_for_hours": 3,
        "ok": sources_ok,
        "headline": headline[:120],
        "metrics": [
            {"label": "M+X flares · 7d", "value": str(len(big_flares))},
            {"label": "CME arrivals pending", "value": str(len(arrivals))},
        ],
        "items": [
            {
                "when_utc": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text": item["text"][:140],
                "url": item["url"],
            }
            for when, item in items[:5]
        ],
    }
