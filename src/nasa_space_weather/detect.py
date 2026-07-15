from __future__ import annotations

from typing import Any, Protocol

from . import config
from .models import CME, Flare, Storm, flare_class_rank


class _Event(Protocol):
    @property
    def activity_id(self) -> str: ...

    def to_state(self) -> dict[str, Any]: ...


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
    if storm.max_kp is None:
        return "info"
    if storm.max_kp >= config.GST_CRITICAL_KP:
        return "critical"
    if storm.max_kp >= config.GST_ALERT_MIN_KP:
        return "high"
    return "info"


def snapshot(items: list[_Event]) -> dict[str, dict[str, Any]]:
    return {item.activity_id: item.to_state() for item in items}


def changed(previous: dict[str, dict[str, Any]], current: list[_Event]) -> list[_Event]:
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
