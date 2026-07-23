"""Dataclasses for DONKI flare, CME, and geomagnetic-storm events, plus their parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Flare class letters rank A < B < C < M < X. Each step is a 10x jump in X-ray flux.
_CLASS_ORDER = {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}


def flare_class_rank(class_type: str) -> int:
    """Rank of a DONKI classType like 'M5.2'. Unknown/empty ranks -1 so it can never
    accidentally clear a threshold."""
    letter = class_type[:1].upper() if class_type else ""
    return _CLASS_ORDER.get(letter, -1)


def parse_time(raw: str | None) -> datetime | None:
    """DONKI stamps look like '2026-07-14T14:36Z'. Return None rather than guessing."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _linked(raw: dict[str, Any]) -> list[str]:
    """DONKI's own causal graph: linkedEvents -> [{'activityID': ...}, ...].
    This is what lets us group a flare, its CME, and the resulting storm into one episode
    without inferring anything ourselves."""
    events = raw.get("linkedEvents") or []
    return [e["activityID"] for e in events if e.get("activityID")]


@dataclass
class Flare:
    """A DONKI FLR (solar flare) event."""

    flr_id: str
    peak_time: datetime | None
    class_type: str
    active_region: int | None
    linked: list[str] = field(default_factory=list)
    link: str = ""

    @property
    def activity_id(self) -> str:
        """The DONKI activity ID, under the name every event type shares."""
        return self.flr_id

    @property
    def rank(self) -> int:
        """Ordinal strength of this flare's class letter, for threshold comparisons."""
        return flare_class_rank(self.class_type)

    def to_state(self) -> dict[str, Any]:
        """Serialise the fields that change detection compares between runs."""
        return {
            "flr_id": self.flr_id,
            "peak_time": self.peak_time.isoformat() if self.peak_time else None,
            "class_type": self.class_type,
            "active_region": self.active_region,
            "linked": self.linked,
            "link": self.link,
        }


@dataclass
class EnlilRun:
    """A WSA-Enlil model run, embedded inside a CME's analysis. This is where the arrival
    countdown comes from."""

    arrival_time: datetime | None
    predicted_kp: float | None
    is_earth_gb: bool

    def to_state(self) -> dict[str, Any]:
        """Serialise the fields that change detection compares between runs."""
        return {
            "arrival_time": self.arrival_time.isoformat() if self.arrival_time else None,
            "predicted_kp": self.predicted_kp,
            "is_earth_gb": self.is_earth_gb,
        }


@dataclass
class CME:
    """A DONKI CME (coronal mass ejection) event, with its best WSA-Enlil analysis."""

    activity_id: str
    start_time: datetime | None
    speed_kms: float | None
    enlil: EnlilRun | None
    has_analysis: bool
    linked: list[str] = field(default_factory=list)
    link: str = ""

    @property
    def is_earth_directed(self) -> bool:
        """Earth-directed means WSA-Enlil predicts it reaches us. No prediction => not
        Earth-directed. `has_analysis` distinguishes 'analysed, harmless' from 'not yet
        analysed' — never let the two look the same to a reader."""
        if self.enlil is None:
            return False
        return self.enlil.arrival_time is not None or self.enlil.is_earth_gb

    def to_state(self) -> dict[str, Any]:
        """Serialise the fields that change detection compares between runs."""
        return {
            "activity_id": self.activity_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "speed_kms": self.speed_kms,
            "enlil": self.enlil.to_state() if self.enlil else None,
            "has_analysis": self.has_analysis,
            "earth_directed": self.is_earth_directed,
            "linked": self.linked,
            "link": self.link,
        }


@dataclass
class Storm:
    """A DONKI GST (geomagnetic storm) event."""

    gst_id: str
    start_time: datetime | None
    max_kp: float | None
    linked: list[str] = field(default_factory=list)
    link: str = ""

    @property
    def activity_id(self) -> str:
        """The DONKI activity ID, under the name every event type shares."""
        return self.gst_id

    def to_state(self) -> dict[str, Any]:
        """Serialise the fields that change detection compares between runs."""
        return {
            "gst_id": self.gst_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "max_kp": self.max_kp,
            "linked": self.linked,
            "link": self.link,
        }


def parse_flares(raw: list[dict[str, Any]]) -> list[Flare]:
    """Convert raw DONKI FLR records into Flare objects, skipping any with no flare ID."""
    out: list[Flare] = []
    for item in raw:
        flr_id = item.get("flrID")
        if not flr_id:
            continue
        region = item.get("activeRegionNum")
        out.append(
            Flare(
                flr_id=flr_id,
                peak_time=parse_time(item.get("peakTime")),
                class_type=item.get("classType") or "",
                active_region=int(region) if region else None,
                linked=_linked(item),
                link=item.get("link") or "",
            )
        )
    return out


def _best_analysis(analyses: list[dict[str, Any]]) -> dict[str, Any] | None:
    """DONKI flags one analysis as most accurate; prefer it, else take the first."""
    if not analyses:
        return None
    for a in analyses:
        if a.get("isMostAccurate"):
            return a
    return analyses[0]


_EPOCH = datetime.min.replace(tzinfo=UTC)


def _latest_enlil_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """DONKI appends a new enlilList entry each time a CME's WSA-Enlil model is rerun with
    better data; later runs supersede earlier ones. A real 30-day capture confirmed this
    matters: one CME's first run predicted no Earth impact (arrival=None, isEarthGB=False)
    and a second run 53 minutes later reversed that to a real impact — NASA sent two
    separate alerts, one per run. Picking anything but the latest risks reporting the
    stale 'no impact' verdict after the model itself has moved on."""
    return max(runs, key=lambda r: parse_time(r.get("modelCompletionTime")) or _EPOCH)


def _enlil_from(analysis: dict[str, Any]) -> EnlilRun | None:
    runs = analysis.get("enlilList") or []
    if not runs:
        return None
    run = _latest_enlil_run(runs)
    kps = [run.get(k) for k in ("kp_18", "kp_90", "kp_135", "kp_180")]
    known = [float(k) for k in kps if k is not None]
    return EnlilRun(
        arrival_time=parse_time(run.get("estimatedShockArrivalTime")),
        predicted_kp=max(known) if known else None,
        is_earth_gb=bool(run.get("isEarthGB")),
    )


def parse_cmes(raw: list[dict[str, Any]]) -> list[CME]:
    """Convert raw DONKI CME records into CME objects, skipping any with no activity ID.

    Speed and the Earth-arrival prediction are taken from the analysis DONKI marks most
    accurate, falling back to the first one present.
    """
    out: list[CME] = []
    for item in raw:
        activity_id = item.get("activityID")
        if not activity_id:
            continue
        analyses = item.get("cmeAnalyses") or []
        best = _best_analysis(analyses)
        speed = best.get("speed") if best else None
        out.append(
            CME(
                activity_id=activity_id,
                start_time=parse_time(item.get("startTime")),
                speed_kms=float(speed) if speed is not None else None,
                enlil=_enlil_from(best) if best else None,
                has_analysis=bool(analyses),
                linked=_linked(item),
                link=item.get("link") or "",
            )
        )
    return out


def parse_storms(raw: list[dict[str, Any]]) -> list[Storm]:
    """Convert raw DONKI GST records into Storm objects, skipping any with no storm ID.

    `max_kp` is the highest reading across the storm's whole Kp series, which is the value
    severity and the aurora latitude estimate are both derived from.
    """
    out: list[Storm] = []
    for item in raw:
        gst_id = item.get("gstID")
        if not gst_id:
            continue
        kps = [k.get("kpIndex") for k in (item.get("allKpIndex") or [])]
        known = [float(k) for k in kps if k is not None]
        out.append(
            Storm(
                gst_id=gst_id,
                start_time=parse_time(item.get("startTime")),
                max_kp=max(known) if known else None,
                linked=_linked(item),
                link=item.get("link") or "",
            )
        )
    return out
