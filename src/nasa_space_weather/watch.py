from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any, Callable

from . import config, episodes, render, site, state
from .detect import changed, snapshot
from .episodes import Episode
from .sinks.github_issues import GitHubIssues
from .sources import cmes, flares, storms

_SOURCES: list[tuple[str, Callable[[], list[Any]]]] = [
    ("flares", flares.fetch),
    ("cmes", cmes.fetch),
    ("storms", storms.fetch),
]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _fetch_all() -> tuple[dict[str, list[Any]], dict[str, bool]]:
    """Fetch every source. A source that fails yields [] and is flagged — its state is then
    NOT advanced, so the next run re-detects whatever it missed. That self-healing is why a
    blip must not fail the whole run."""
    results: dict[str, list[Any]] = {}
    ok: dict[str, bool] = {}
    for name, fetch in _SOURCES:
        try:
            results[name] = fetch()
            ok[name] = True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"source {name}: fetch failed: {exc}", file=sys.stderr)
            results[name] = []
            ok[name] = False
    return results, ok


def report(streaks: dict[str, int]) -> None:
    """Decide how loudly to complain about the sources that failed this run.

    Warn while a source is merely flapping; escalate to a hard failure only once it has been
    down long enough that we may genuinely be blind to something. Failing the whole job over
    a transient 502 only trains us to ignore a red X.

    Workflow commands are read from STDOUT, so these prints must NOT go to stderr, or the
    annotation silently never surfaces on the run.
    """
    down = {name: n for name, n in sorted(streaks.items()) if n > 0}

    if down and len(down) == len(_SOURCES):
        # Every DONKI source shares one host, one API key and one quota. All of them failing
        # together is one shared-upstream problem, not N independent blips — say it once.
        worst = max(down.values())
        print(
            f"::warning::all DONKI sources unavailable ({worst} run(s) in a row) — "
            f"this is almost certainly api.nasa.gov itself (shared host/key/quota), "
            f"not {len(down)} coincidental failures"
        )
    else:
        for name, count in down.items():
            print(f"::warning::source {name} unavailable ({count} run(s) in a row)")

    sustained = [n for n, c in down.items() if c >= config.SOURCE_FAILURE_LIMIT]
    if sustained:
        raise RuntimeError(
            f"source(s) down for {config.SOURCE_FAILURE_LIMIT}+ consecutive runs: "
            f"{', '.join(sorted(sustained))}"
        )


def _save_meta(state_dir: Path, streaks: dict[str, int]) -> None:
    state.save(
        state_dir / "meta.json",
        {
            "schema_version": config.SCHEMA_VERSION,
            "last_run_utc": _now(),
            "cold_start": False,
            "consecutive_failures": streaks,
        },
    )


def run(dry_run: bool = False) -> list[Episode]:
    # pylint: disable=too-many-locals
    state_dir = config.STATE_DIR
    meta = state.load(state_dir / "meta.json")
    streaks: dict[str, int] = dict(meta.get("consecutive_failures") or {})
    is_cold_start = meta.get("cold_start", True)

    fetched, ok = _fetch_all()
    for name, succeeded in ok.items():
        streaks[name] = 0 if succeeded else streaks.get(name, 0) + 1

    all_flares, all_cmes, all_storms = fetched["flares"], fetched["cmes"], fetched["storms"]

    prior_episodes = state.load(state_dir / "episodes.json")
    built, episode_state = episodes.assemble(all_flares, all_cmes, all_storms, prior_episodes)

    events: dict[str, Any] = {e.activity_id: e for e in [*all_flares, *all_cmes, *all_storms]}

    # Only episodes containing something new/changed AND rated above `info` earn an Issue.
    delta_ids = {
        item.activity_id
        for name, items in (("flares", all_flares), ("cmes", all_cmes), ("storms", all_storms))
        if ok[name]
        for item in changed(state.load(state_dir / f"{name}.json"), items)
    }
    actionable = [
        ep
        for ep in built
        if ep.severity != "info" and any(m.activity_id in delta_ids for m in ep.members)
    ]

    # First ever run: seed the baseline from the fetch window but create NO Issues, so the
    # watcher never floods the repo with the whole backlog. Real alerting starts next run.
    sink = None if (dry_run or is_cold_start) else GitHubIssues.from_env()
    if is_cold_start and not dry_run:
        print(
            f"::warning::cold start — seeding baseline from the last "
            f"{config.FETCH_LOOKBACK_DAYS} days and suppressing {len(actionable)} initial "
            f"Issue(s); real alerts begin next run"
        )
    issue_numbers = {
        key: meta_entry.get("issue_number")
        for key, meta_entry in (episode_state.get("episodes") or {}).items()
        if meta_entry.get("issue_number")
    }

    upsert_failed = False
    for episode in actionable:
        title = render.issue_title(episode, events)
        body = render.issue_body(episode, events, issue_numbers)
        labels = render.labels_for(episode, events)
        if dry_run or sink is None:
            label = "cold-start seed" if is_cold_start else "dry-run"
            print(f"[{label}] {episode.key}: {title}", file=sys.stderr)
            continue
        try:
            result = sink.upsert(episode.key, title, body, labels)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # One Issue failing to post must not sink the whole run: the streak counter
            # still has to persist, and this episode must re-detect next run rather than be
            # silently lost. Warn (STDOUT, so Actions surfaces it), flag, and carry on.
            print(f"::warning::issue upsert failed for {episode.key} ({exc}); will retry next run")
            upsert_failed = True
            continue
        episode_state["episodes"][episode.key]["issue_number"] = result["number"]

    if not dry_run:
        # Persist BEFORE reporting: `report` may raise, and the streak counter it reads on
        # the next run has to survive a failing run in order to be able to count at all.
        # A source snapshot is advanced only when the source succeeded AND every Issue this
        # run upserted cleanly — otherwise a missed Issue would never be re-detected. The
        # episode key-map and streaks are ALWAYS persisted (they must survive regardless).
        for name, items in (("flares", all_flares), ("cmes", all_cmes), ("storms", all_storms)):
            if ok[name] and not upsert_failed:  # hold back state if any Issue was lost
                state.save(state_dir / f"{name}.json", snapshot(items))
        state.save(state_dir / "episodes.json", episode_state)
        _save_meta(state_dir, streaks)
        if config.SITE_ENABLED:
            site.render_site(built, events, config.SITE_DIR)

    report(streaks)
    return actionable
