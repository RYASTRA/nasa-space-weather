"""Severity scoring, relevance windowing, and snapshot diffing for DONKI events."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol

from . import config
from .models import CME, Flare, Storm, flare_class_rank


class _Event(Protocol):
    # The ellipsis bodies are what make these structural stubs rather than methods that
    # return None; pylint reads them as redundant beside the docstring, type checkers do not.
    # pylint: disable=unnecessary-ellipsis

    @property
    def activity_id(self) -> str:
        """The DONKI activity ID identifying this event."""
        ...

    def to_state(self) -> dict[str, Any]:
        """Serialise this event for snapshot comparison."""
        ...


def flare_severity(flare: Flare) -> str:
    """A/B/C flares are near-daily noise -> `info` (suppressed on their own). They still
    surface as context inside a live episode, and can trigger a swarm (see episodes.py)."""
    rank = flare.rank
    if rank >= flare_class_rank(config.FLARE_CRITICAL_CLASS):
        return "critical"
    if rank >= flare_class_rank(config.FLARE_ALERT_MIN_CLASS):
        return "high"
    return "info"


def cme_severity(cme: CME) -> str:
    """Only Earth-directed CMEs matter to any of our audiences. A CME off the far limb is
    irrelevant; an unanalysed one is `info` — but `has_analysis` keeps it distinguishable
    from an analysed-and-harmless one, which render.py must surface."""
    if not cme.is_earth_directed:
        return "info"
    fast = cme.speed_kms is not None and cme.speed_kms >= config.CME_FAST_KMS
    stormy = (
        cme.enlil is not None
        and cme.enlil.predicted_kp is not None
        and cme.enlil.predicted_kp >= config.GST_CRITICAL_KP
    )
    return "critical" if fast or stormy else "high"


def storm_severity(storm: Storm) -> str:
    """Severity for a geomagnetic storm, from its peak Kp index.

    A storm with no Kp reading yet scores `info` rather than being guessed at — DONKI
    publishes the record before the index series is populated.
    """
    if storm.max_kp is None:
        return "info"
    if storm.max_kp >= config.GST_CRITICAL_KP:
        return "critical"
    if storm.max_kp >= config.GST_ALERT_MIN_KP:
        return "high"
    return "info"


def is_active(event: object, now: dt.datetime) -> bool:
    """True when an event's effects are still upcoming or recent — the rule that makes this a
    forecast/nowcast instead of a history dump. A CME is judged by its predicted Earth arrival
    (a FUTURE arrival is the whole point of the forecast), falling back to eruption time before
    it is analysed; a storm and a flare by when they occurred. An explicit Earth-impact
    flag remains active when DONKI omits both timestamps: without a time, we cannot safely
    age out a known impact. Anything older than RELEVANCE_WINDOW_H is not active; future
    timestamps always pass.
    """
    when: dt.datetime | None
    if isinstance(event, CME):
        when = (
            event.enlil.arrival_time
            if (event.enlil and event.enlil.arrival_time)
            else event.start_time
        )
        if when is None:
            return event.is_earth_directed
    elif isinstance(event, Storm):
        when = event.start_time
    elif isinstance(event, Flare):
        when = event.peak_time
    else:
        return False
    if when is None:
        return False
    return when >= now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)


def snapshot(items: Sequence[_Event]) -> dict[str, dict[str, Any]]:
    """Map events by activity ID to their serialised state, to persist as the next baseline."""
    return {item.activity_id: item.to_state() for item in items}


def changed(previous: dict[str, dict[str, Any]], current: Sequence[_Event]) -> list[_Event]:
    """New items, plus items whose state materially differs from the snapshot.

    Comparing whole state dicts (rather than hand-picking fields) means a CME that gains an
    arrival prediction, or a storm whose Kp climbs, is correctly seen as a NEW fact worth
    re-announcing — without us having to enumerate every field that might move.
    """
    out: list[_Event] = []
    for item in current:
        prior = previous.get(item.activity_id)
        if prior is None or prior != item.to_state():
            out.append(item)
    return out
