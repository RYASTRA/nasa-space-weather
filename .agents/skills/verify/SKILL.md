---
name: verify
description: Project-specific runtime verification recipe for nasa-space-weather (CLI orchestrator)
---

# Verifying nasa-space-weather

This is a CLI tool with no server/GUI. The surface is `python -m nasa_space_weather [--dry-run]`.

## Setup

- Needs `NASA_API_KEY` env var (or `.env`, loaded by `config.load_dotenv()`, called only
  from `__main__.main()` — not from `watch.run()` directly). `DEMO_KEY` works against the
  real live api.nasa.gov and is rate-limited but fine for a handful of manual runs.
- Redirect state/site away from the repo tree while poking at it:
  `NASA_SPACE_WEATHER_STATE_DIR=<scratch>/state NASA_SPACE_WEATHER_SITE_DIR=<scratch>/site`
  (both default to `state/` and `site/` at repo root otherwise — real, committed paths).
- `--dry-run` skips `GitHubIssues.from_env()` entirely, so it never needs `GITHUB_TOKEN` /
  `GITHUB_REPOSITORY`. Without `--dry-run`, `GitHubIssues.from_env()` is constructed
  *unconditionally* (even on a day with zero actionable episodes) — the real run needs both
  env vars set even when nothing will be upserted. The constructor itself makes no network
  call, so dummy values are safe to use for testing the persistence path AS LONG AS you've
  confirmed zero episodes will be actionable (e.g. all sources failed → no events at all),
  since only `.upsert()` actually calls the GitHub API.

## Driving each behavior live (no mocks needed)

- **Happy path / real fetch+assemble+render**: set a real key, `--dry-run`, run it. Prints
  `[dry-run] would upsert ...` per actionable episode, then `N actionable episode(s)` on
  stderr. Confirm scratch state/site dirs stay empty afterward (dry-run truly writes nothing).
- **Source-down blip**: `unset NASA_API_KEY` — `config.nasa_api_key()` raises deterministically
  for all 3 sources with zero network calls, no flakiness. First time (empty/no prior meta):
  one merged `::warning::...api.nasa.gov...` line on stdout, per-source diagnostics on stderr,
  exit 0.
- **Escalation**: pre-seed `<scratch>/state/meta.json` via `state.save(path, {"schema_version":
  1, "last_run_utc": "...", "consecutive_failures": {"flares": 2, "cmes": 2, "storms": 2}})`,
  then repeat the blip run. Streak hits 3 → `::error::...` also on stdout, exit 1.
- **Persist-before-raise**: repeat the escalation run WITHOUT `--dry-run` (dummy GITHUB_TOKEN/
  GITHUB_REPOSITORY are fine here since all sources failing means zero actionable episodes,
  so `.upsert()` never fires). Confirm `meta.json` on disk shows the bumped streak (3) even
  though the process exits 1 — proves `_save_meta` truly ran before `report()` raised.
- **Self-healing state**: after a failed non-dry-run, check the scratch state dir — only
  `episodes.json` and `meta.json` should exist; `flares.json`/`cmes.json`/`storms.json` must
  be ABSENT (failed sources never advance their snapshot).
- **Recovery**: re-run with a valid key — streaks recompute to 0 for any source that
  succeeded this run and `report()` goes silent (no warning/error, exit 0). Under `--dry-run`
  this reset is NOT persisted (by design); only a real run writes it back.

## Gotchas

- Bash tool calls do not share shell state — env vars exported in one call are gone in the
  next. Re-export per call, or chain with `&&`/`;` inside one call.
- `sources/http.py` uses `except KeyError, ValueError:` (no parens) — that's Python 3.14's
  PEP 758 unparenthesized-except, not a typo. This repo requires `>=3.14`.
