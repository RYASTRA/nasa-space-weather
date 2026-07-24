"""Shared event-selection semantics for the HTML and Observatory status views."""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import config
from .episodes import Episode
from .models import CME, Flare, Storm, flare_class_rank


def episode_events(episodes: list[Episode], events: dict[str, Any]) -> list[Any]:
    """Return unique event objects represented by the current episode graph."""
    seen: dict[str, Any] = {}
    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if event is not None:
                seen.setdefault(member.activity_id, event)
    return list(seen.values())


def recent_storms(events: list[Any], now: dt.datetime) -> list[Storm]:
    """Storm records that began inside the configured relevance window."""
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    return [
        event
        for event in events
        if isinstance(event, Storm) and event.start_time is not None and event.start_time >= cutoff
    ]


def recent_major_flares(events: list[Any], now: dt.datetime) -> list[Flare]:
    """M/X-class flares inside the public activity view's seven-day window."""
    week_ago = now - dt.timedelta(days=7)
    minimum_rank = flare_class_rank("M")
    return [
        event
        for event in events
        if isinstance(event, Flare)
        and event.peak_time is not None
        and event.peak_time >= week_ago
        and event.rank >= minimum_rank
    ]


def _is_pending_earth_impact(event: Any, cutoff: dt.datetime) -> bool:
    """Narrow a catalog object to a relevant EarthGB result without an ETA."""
    if not isinstance(event, CME) or not event.has_analysis or event.enlil is None:
        return False
    if not event.enlil.is_earth_gb or event.enlil.arrival_time is not None:
        return False
    return event.start_time is None or event.start_time >= cutoff


def pending_earth_impacts(
    episodes: list[Episode], events: dict[str, Any], now: dt.datetime
) -> list[CME]:
    """Relevant ETA-pending impacts, deduplicated only inside NASA-linked episodes."""
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    selected: dict[tuple[str, str], CME] = {}
    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if not _is_pending_earth_impact(event, cutoff):
                continue
            start_key = event.start_time.isoformat() if event.start_time is not None else "unknown"
            key = episode.key, start_key
            previous = selected.get(key)
            if previous is None or _arrival_priority(event) > _arrival_priority(previous):
                selected[key] = event
    return list(selected.values())


def activity_cmes(episodes: list[Episode], events: dict[str, Any], now: dt.datetime) -> list[CME]:
    """Seven-day Earth-relevant CMEs, deduplicated within NASA-linked episodes."""
    week_ago = now - dt.timedelta(days=7)
    selected: dict[tuple[str, str, str], CME] = {}
    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if (
                not isinstance(event, CME)
                or not event.is_earth_directed
                or (event.start_time is not None and event.start_time < week_ago)
            ):
                continue
            start_key = event.start_time.isoformat() if event.start_time is not None else "unknown"
            arrival = event.enlil.arrival_time if event.enlil is not None else None
            arrival_key = arrival.isoformat() if arrival is not None else "pending"
            key = episode.key, start_key, arrival_key
            previous = selected.get(key)
            if previous is None or _arrival_priority(event) > _arrival_priority(previous):
                selected[key] = event
    return list(selected.values())


def _arrival_priority(cme: CME) -> tuple[float, float]:
    """Prefer the strongest telling when catalog records share one shock time."""
    predicted_kp = cme.enlil.predicted_kp if cme.enlil is not None else None
    kp_score = predicted_kp if predicted_kp is not None else -1.0
    speed_score = cme.speed_kms if cme.speed_kms is not None else -1.0
    return kp_score, speed_score


def arrival_buckets(events: list[Any], now: dt.datetime) -> tuple[list[CME], list[CME]]:
    """Future and recent modelled CME times, deduplicated by predicted shock time."""
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    future: dict[str, CME] = {}
    recent: dict[str, CME] = {}
    for event in events:
        if not isinstance(event, CME) or not event.has_analysis or event.enlil is None:
            continue
        arrival = event.enlil.arrival_time
        if arrival is None or arrival < cutoff:
            continue
        bucket = future if arrival >= now else recent
        key = arrival.isoformat()
        previous = bucket.get(key)
        if previous is None or _arrival_priority(event) > _arrival_priority(previous):
            bucket[key] = event
    return list(future.values()), list(recent.values())
