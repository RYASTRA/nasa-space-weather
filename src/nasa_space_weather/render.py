"""Issue title, label, and body templates for an episode."""

from __future__ import annotations

import datetime as dt
from typing import Any

from .episodes import Episode
from .models import CME, Flare, Storm, flare_class_rank
from .sinks.github_issues import BASE_LABEL, key_marker

_TYPE_LABEL = {"FLR": "solar-flare", "CME": "cme", "GST": "geomagnetic-storm"}


def _stamp(when: dt.datetime | None) -> str:
    return when.strftime("%Y-%m-%d %H:%M UTC") if when else "time unknown"


def radio_blackout(class_type: str) -> str:
    """Flare class -> NOAA R-scale. A lookup, not a judgement — for the radio amateurs."""
    rank = flare_class_rank(class_type)
    if rank >= flare_class_rank("X"):
        return (
            "R3+ — strong HF radio blackout on the daylit side; "
            "loss of contact for tens of minutes."
        )
    if rank >= flare_class_rank("M"):
        return "R1-R2 — minor to moderate HF degradation on the daylit side."
    return "Below R1 — no meaningful radio impact expected."


def aurora_latitude(kp: float) -> str:
    """Kp -> how far south aurora becomes plausible. For the aurora chasers."""
    if kp >= 8:
        return "Aurora plausible down to ~40 deg geomagnetic latitude."
    if kp >= 7:
        return "Aurora plausible down to ~45 deg geomagnetic latitude."
    if kp >= 6:
        return "Aurora plausible down to ~50 deg geomagnetic latitude."
    if kp >= 5:
        return "Aurora plausible down to ~55 deg geomagnetic latitude (high latitudes)."
    return "Aurora confined to polar latitudes."


def satellite_note(kp: float) -> str:
    """For the satellite operators."""
    if kp >= 7:
        return "Increased atmospheric drag in LEO and elevated surface-charging risk."
    if kp >= 5:
        return "Mild drag increase possible; monitor charging on sensitive spacecraft."
    return "No significant spacecraft impact expected."


def _cme_lines(cme: CME) -> list[str]:
    lines = [f"- **CME** {_stamp(cme.start_time)}"]
    if cme.speed_kms is not None:
        lines.append(f"  - Speed: {cme.speed_kms:.0f} km/s")
    if not cme.has_analysis:
        # SILENCE READS AS SAFE. Never omit the countdown — say that it is missing.
        lines.append("  - Arrival prediction: **not yet available** (CME not yet analysed).")
        return lines
    if cme.enlil is None:
        # Analysed, but no WSA-Enlil run yet: we have no arrival prediction, so make NO
        # claim about Earth impact — absence of a prediction is not a prediction of safety.
        lines.append("  - Arrival prediction: **not yet available** (no WSA-Enlil run yet).")
        return lines
    if cme.enlil.arrival_time is None:
        # A run completed but gave no shock-arrival time. If it still flags Earth impact,
        # say so LOUDLY — an Earth-directed CME must never render as harmless (spec 8.6).
        if cme.is_earth_directed:
            lines.append("  - **Earth impact expected** — shock arrival time not yet estimated.")
        else:
            lines.append("  - Analysed: not currently predicted to reach Earth.")
        return lines
    lines.append(f"  - **Predicted Earth arrival: {_stamp(cme.enlil.arrival_time)}**")
    if cme.enlil.predicted_kp is not None:
        lines.append(f"  - Predicted Kp {cme.enlil.predicted_kp:.0f}")
        lines.append(f"  - {aurora_latitude(cme.enlil.predicted_kp)}")
    return lines


def _event_lines(event: Any) -> list[str]:
    if isinstance(event, Flare):
        return [
            f"- **Solar flare {event.class_type}** peaked {_stamp(event.peak_time)}"
            + (f" (active region {event.active_region})" if event.active_region else ""),
            f"  - {radio_blackout(event.class_type)}",
        ]
    if isinstance(event, CME):
        return _cme_lines(event)
    if isinstance(event, Storm):
        kp = event.max_kp
        lines = [f"- **Geomagnetic storm** began {_stamp(event.start_time)}"]
        if kp is not None:
            lines.append(f"  - **Kp {kp:.0f}**")
            lines.append(f"  - {aurora_latitude(kp)}")
            lines.append(f"  - {satellite_note(kp)}")
        return lines
    return []


def issue_title(episode: Episode, _events: dict[str, Any]) -> str:
    # `_events` kept for interface symmetry with issue_body/labels_for; unused in titles.
    """Headline for an episode's issue, named for the most consequential event in it."""
    present = {m.event_type for m in episode.members}
    if "GST" in present:
        headline = "Geomagnetic storm"
    elif "CME" in present:
        headline = "Earth-directed CME"
    elif episode.swarm_regions:
        headline = f"Active region {episode.swarm_regions[0]} flaring repeatedly"
    else:
        headline = "Solar flare"
    return f"[{episode.severity}] {headline}"


def labels_for(episode: Episode, events: dict[str, Any]) -> list[str]:
    """Issue labels for an episode, tagging event types, flare swarms, and aurora-class storms."""
    labels = [BASE_LABEL, f"severity-{episode.severity}"]
    for member in episode.members:
        label = _TYPE_LABEL.get(member.event_type)
        if label and label not in labels:
            labels.append(label)
    if episode.swarm_regions:
        labels.append("active-region")
    if any(
        isinstance(events.get(m.activity_id), Storm) and (events[m.activity_id].max_kp or 0) >= 5
        for m in episode.members
    ):
        labels.append("aurora")
    return labels


def issue_body(episode: Episode, events: dict[str, Any], issue_numbers: dict[str, int]) -> str:
    """Full issue body for an episode, including its key marker and any linked issue numbers."""
    parts: list[str] = [key_marker(episode.key), ""]
    parts.append(f"**Severity: {episode.severity}**")
    parts.append("")

    if episode.swarm_regions:
        regions = ", ".join(str(r) for r in episode.swarm_regions)
        parts.append(
            f"> Active region(s) {regions} are firing repeatedly. No single flare is large, "
            f"but a cluster like this is a genuine precursor signal."
        )
        parts.append("")

    parts.append("## What happened")
    parts.append("")
    for member in episode.members:
        event = events.get(member.activity_id)
        if event is not None:
            parts.extend(_event_lines(event))
    parts.append("")

    related = [issue_numbers.get(k) for k in episode.related_keys]
    linked = [f"#{n}" for n in related if n]
    if linked:
        parts.append(f"**Related episodes:** {', '.join(linked)}")
        parts.append("")

    parts.append("## Sources")
    parts.append("")
    for member in episode.members:
        event = events.get(member.activity_id)
        link = getattr(event, "link", "") if event else ""
        suffix = f" — [DONKI]({link})" if link else ""
        parts.append(f"- `{member.activity_id}`{suffix}")

    return "\n".join(parts)
