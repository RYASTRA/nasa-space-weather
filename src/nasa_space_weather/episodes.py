"""Grouping of causally linked DONKI events into single episodes.

A flare, the CME it launched, and the storm that CME caused are one story, and DONKI's own
`linkedEvents` graph says which events belong together — so the grouping is read from the
upstream data rather than inferred here.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import config
from .detect import cme_severity, flare_severity, storm_severity
from .models import CME, Flare, Storm, flare_class_rank

_ORDER = {"info": 0, "high": 1, "critical": 2}


def _rank(severity: str) -> int:
    return _ORDER[severity]


def _highest(severities: list[str]) -> str:
    return max(severities, key=_rank) if severities else "info"


@dataclass
class Member:
    """One DONKI event (flare, CME, or storm) as it participates in an episode."""

    activity_id: str
    event_type: str  # "FLR" | "CME" | "GST"
    severity: str


@dataclass
class Episode:
    """A cluster of linked events rated and reported as a single evolving story."""

    key: str
    members: list[Member]
    severity: str
    swarm_regions: list[int] = field(default_factory=list)
    related_keys: list[str] = field(default_factory=list)


def swarming_regions(flares: list[Flare]) -> set[int]:
    """Active regions that fired FLARE_SWARM_COUNT+ flares of at least FLARE_SWARM_MIN_CLASS
    within FLARE_SWARM_WINDOW_H. An active region firing repeatedly is a genuine precursor
    signal even when no single flare is large — this is the "multiple small things" rule.
    """
    floor = flare_class_rank(config.FLARE_SWARM_MIN_CLASS)
    window = dt.timedelta(hours=config.FLARE_SWARM_WINDOW_H)

    by_region: dict[int, list[dt.datetime]] = defaultdict(list)
    for flare in flares:
        if flare.active_region is None or flare.peak_time is None:
            continue
        if flare.rank >= floor:
            by_region[flare.active_region].append(flare.peak_time)

    swarming: set[int] = set()
    for region, times in by_region.items():
        times.sort()
        for i, anchor in enumerate(times):
            in_window = sum(1 for t in times[i:] if t - anchor <= window)
            if in_window >= config.FLARE_SWARM_COUNT:
                swarming.add(region)
                break
    return swarming


def compound_severity(members: list[Member], has_swarm: bool, max_kp: float | None) -> str:
    """Rate the episode as a whole, not as a bag of independent events.

    Baseline is the max of the parts. A swarm sets a FLOOR of `high` (never critical on its
    own — that would make every routine active region scream). Escalation to `critical`
    requires signals of two DIFFERENT kinds stacking up, which is the case worth waking
    someone for: a flare AND an Earth-directed CME, or a swarm beside a CME.

    `info` members are context only: they never escalate anything by themselves.
    """
    severities = [m.severity for m in members]
    qualifying_types = {m.event_type for m in members if _rank(m.severity) >= _rank("high")}

    if has_swarm:
        # The swarm itself is a `high` signal, and it is of type FLR — so it can pair with a
        # CME/GST to escalate, exactly like a single large flare would.
        severities.append("high")
        qualifying_types.add("FLR")

    base = _highest(severities)

    if max_kp is not None and max_kp >= config.GST_CRITICAL_KP:
        return "critical"
    if base == "high" and len(qualifying_types) >= 2:
        return "critical"
    return base


def _adjacency(
    flares: list[Flare], cmes: list[CME], storms: list[Storm]
) -> tuple[dict[str, set[str]], dict[str, Member]]:
    """Build DONKI's causal graph. Edges are bidirectional: only one side of a pair may
    declare the link, and we must find the cluster either way."""
    members: dict[str, Member] = {}
    graph: dict[str, set[str]] = defaultdict(set)

    def add(activity_id: str, event_type: str, severity: str, linked: list[str]) -> None:
        members[activity_id] = Member(activity_id, event_type, severity)
        # defaultdict access materialises the node even when it has no edges
        graph[activity_id].update(linked)
        for other in linked:
            graph[other].add(activity_id)

    for flare in flares:
        add(flare.activity_id, "FLR", flare_severity(flare), flare.linked)
    for cme in cmes:
        add(cme.activity_id, "CME", cme_severity(cme), cme.linked)
    for storm in storms:
        add(storm.activity_id, "GST", storm_severity(storm), storm.linked)

    return graph, members


def _clusters(graph: dict[str, set[str]], known: set[str]) -> list[list[str]]:
    """Connected components, restricted to activity IDs we actually hold. DONKI may link to
    an event outside our fetch window; we ignore dangling references rather than inventing
    members for them."""
    seen: set[str] = set()
    out: list[list[str]] = []
    for node in sorted(known):
        if node in seen:
            continue
        stack, cluster = [node], []
        seen.add(node)
        while stack:
            current = stack.pop()
            cluster.append(current)
            for neighbour in graph.get(current, ()):
                if neighbour in known and neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        out.append(sorted(cluster))
    return out


def assemble(
    flares: list[Flare],
    cmes: list[CME],
    storms: list[Storm],
    prior: dict[str, Any],
) -> tuple[list[Episode], dict[str, Any]]:
    """Group linked events into episodes and rate each as a whole.

    KEY STABILITY IS THE WHOLE GAME. An episode's key is minted ONCE, at first sight, and
    persisted in `prior["members"]`. It is never recomputed from the cluster's contents,
    because DONKI linkage arrives over time: if a later run links in an event EARLIER than
    the current root, a derived key would change, `upsert` would miss its marker, and it
    would fork a duplicate Issue.
    """
    # pylint: disable=too-many-locals
    graph, member_index = _adjacency(flares, cmes, storms)
    known = set(member_index)

    member_keys: dict[str, str] = dict(prior.get("members") or {})
    episode_meta: dict[str, Any] = dict(prior.get("episodes") or {})

    swarm_regions = swarming_regions(flares)
    region_of = {f.activity_id: f.active_region for f in flares}
    kp_of = {s.activity_id: s.max_kp for s in storms}

    grouped: dict[str, list[str]] = defaultdict(list)
    cluster_keys: dict[str, set[str]] = defaultdict(set)

    for cluster in _clusters(graph, known):
        existing = [member_keys[a] for a in cluster if a in member_keys]
        if existing:
            # Reuse the key this cluster already answers to. If members carry two DIFFERENT
            # keys, two separate Issues already exist for what turns out to be one episode:
            # v1 cross-links them rather than merging (merging two open Issues is v2).
            primary = sorted(set(existing))[0]
            distinct = sorted(set(existing))
        else:
            primary = f"episode:{min(cluster)}"  # first sight only — minted, then frozen
            distinct = [primary]

        for activity_id in cluster:
            member_keys.setdefault(activity_id, primary)
            grouped[member_keys[activity_id]].append(activity_id)
            cluster_keys[member_keys[activity_id]].update(distinct)

    out: list[Episode] = []
    for key, activity_ids in grouped.items():
        members = [member_index[a] for a in sorted(activity_ids)]
        regions = sorted(
            {
                region
                for a in activity_ids
                if (region := region_of.get(a)) is not None and region in swarm_regions
            }
        )
        kps = [kp for a in activity_ids if (kp := kp_of.get(a)) is not None]
        related = sorted(cluster_keys[key] - {key})
        out.append(
            Episode(
                key=key,
                members=members,
                severity=compound_severity(
                    members, has_swarm=bool(regions), max_kp=max(kps) if kps else None
                ),
                swarm_regions=regions,
                related_keys=related,
            )
        )
        meta = episode_meta.setdefault(key, {"issue_number": None, "related_keys": []})
        meta["related_keys"] = related

    new_state = {"members": member_keys, "episodes": episode_meta}
    return sorted(out, key=lambda e: e.key), new_state
