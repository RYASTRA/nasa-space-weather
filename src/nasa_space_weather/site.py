"""Static HTML dashboard rendered from the current episodes and events."""

from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Any

from . import config
from .episodes import Episode
from .models import CME, Storm
from .render import aurora_latitude

_AURORA_GUIDE = [
    (5, "~55 deg — high latitudes (Scotland, Scandinavia, Canada)"),
    (6, "~50 deg — northern UK, northern US border states"),
    (7, "~45 deg — mid-latitudes; much of the northern US, central Europe"),
    (8, "~40 deg — well into the mid-latitudes"),
]

_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Space-Weather Watch</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
          max-width: 880px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5;
          color: #c9d1d9; background: #0d1117; }}
  h1 {{ font-size: 1.6rem; color: #e6edf3; }}
  h2 {{ margin-top: 2rem; border-bottom: 1px solid #30363d; padding-bottom: .3rem;
        color: #e6edf3; }}
  a {{ color: #58a6ff; }}
  .sev-critical {{ border-left: 4px solid #ff7b72; padding-left: .75rem; }}
  .sev-high {{ border-left: 4px solid #ffa657; padding-left: .75rem; }}
  .sev-info {{ border-left: 4px solid #8b949e; padding-left: .75rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .92rem; }}
  th {{ color: #8b949e; }}
  td, th {{ text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #21262d; }}
  footer {{ margin-top: 3rem; color: #8b949e; font-size: .85rem; }}
</style>
<h1>Space-Weather Watch</h1>
<p>Generated {generated} — data from
   <a href="https://api.nasa.gov/">NASA DONKI</a>.</p>

<h2>Incoming arrivals</h2>
{arrivals}

<h2>Current conditions</h2>
{conditions}

<h2>Will I see aurora?</h2>
<table>
  <tr><th>Kp</th><th>Aurora plausible down to</th></tr>
  {aurora_rows}
</table>

<footer>No servers, no database, no LLM. Every line here is a deterministic
render of NASA's own data.</footer>
"""


def _stamp(when: dt.datetime | None) -> str:
    return when.strftime("%Y-%m-%d %H:%M UTC") if when else "unknown"


def _no_arrival_status(cme: CME) -> str:
    """Why this CME has no arrival countdown — four DISTINCT states, wording shared with
    render.py. The models.py invariant applies on the page too: 'analysed, harmless' and
    'not yet analysed' must never look the same to a reader, and an Earth-directed CME
    must never render as merely pending (spec 8.6)."""
    if not cme.has_analysis:
        return "<strong>arrival prediction not yet available</strong> (not yet analysed)"
    if cme.enlil is None:
        return "<strong>arrival prediction not yet available</strong> (no WSA-Enlil run yet)"
    if cme.enlil.is_earth_gb:
        return "<strong>Earth impact expected</strong> — shock arrival time not yet estimated"
    return "analysed: not currently predicted to reach Earth"


def _arrivals(episodes: list[Episode], events: dict[str, Any], now: dt.datetime) -> str:
    # pylint: disable=too-many-locals
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    rank = {"info": 0, "high": 1, "critical": 2}
    pending: list[str] = []
    best: dict[str, tuple[int, str]] = {}  # arrival iso → (severity rank, row)
    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if not isinstance(event, CME):
                continue
            if not event.has_analysis or event.enlil is None or event.enlil.arrival_time is None:
                # SILENCE READS AS SAFE — never just drop the row. But only for a CME that
                # erupted recently: a stale row has nothing upcoming to warn about, so it
                # is not forward-looking.
                if event.start_time is None or event.start_time < cutoff:
                    continue
                row = (
                    f'<li class="sev-{html.escape(episode.severity)}">CME '
                    f"{html.escape(_stamp(event.start_time))} — "
                    f"{_no_arrival_status(event)}</li>"
                )
                if row not in pending:  # linked CMEs can duplicate a row — one is enough
                    pending.append(row)
                continue
            arrival = event.enlil.arrival_time
            if arrival < cutoff:
                # Predicted arrival already came and went well outside the window — this
                # CME's effects are over, so it no longer belongs on a forward-looking page.
                continue
            kp = event.enlil.predicted_kp
            kp_text = f" — predicted Kp {kp:.0f}. {aurora_latitude(kp)}" if kp is not None else ""
            # Honest tense: a shock that already hit (still inside the window, so the storm
            # may be ongoing) must not read as if it were still on its way.
            verb = "Arrives" if arrival >= now else "Arrived"
            row = (
                f'<li class="sev-{html.escape(episode.severity)}" '
                f'data-arrival="{html.escape(arrival.isoformat())}">'
                f"<strong>{verb} {html.escape(_stamp(arrival))}</strong>"
                f"{html.escape(kp_text)}</li>"
            )
            # One physical shock, one row: DONKI often carries several catalog entries whose
            # Enlil runs converge on the same arrival moment. Keep the severest telling.
            iso = arrival.isoformat()
            member_rank = rank.get(episode.severity, 0)
            prev = best.get(iso)
            if prev is None or member_rank > prev[0]:
                best[iso] = (member_rank, row)
    rows = [row for _, row in best.values()] + pending
    return f"<ul>{''.join(rows)}</ul>" if rows else "<p>Nothing inbound.</p>"


def _conditions(episodes: list[Episode], events: dict[str, Any], now: dt.datetime) -> str:
    cutoff = now - dt.timedelta(hours=config.RELEVANCE_WINDOW_H)
    storms = [
        events[m.activity_id]
        for ep in episodes
        for m in ep.members
        if isinstance(events.get(m.activity_id), Storm)
    ]
    active = [
        s
        for s in storms
        if s.max_kp is not None and s.start_time is not None and s.start_time >= cutoff
    ]
    if not active:
        return "<p>Geomagnetically quiet.</p>"
    worst = max(active, key=lambda s: s.max_kp or 0)
    return (
        f"<p><strong>Kp {worst.max_kp:.0f}</strong> — "
        f"{html.escape(aurora_latitude(worst.max_kp))}</p>"
    )


def render_site(
    episodes: list[Episode],
    events: dict[str, Any],
    out_dir: Path,
    *,
    sources_ok: bool = True,
) -> Path:
    # imported here, not at module top, so status can reuse this module freely
    """Write the dashboard and status.json into `out_dir`, returning the HTML path.

    `sources_ok` is threaded through to status.json so a consumer can tell a genuinely quiet
    sun from a run where the upstream fetch failed.
    """
    from . import status  # pylint: disable=import-outside-toplevel,cyclic-import

    out_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    (out_dir / "status.json").write_text(
        json.dumps(status.build(episodes, events, now, sources_ok=sources_ok), indent=1) + "\n",
        encoding="utf-8",
    )
    page = _PAGE.format(
        generated=now.strftime("%Y-%m-%d %H:%M UTC"),
        arrivals=_arrivals(episodes, events, now),
        conditions=_conditions(episodes, events, now),
        aurora_rows="".join(
            f"<tr><td>{kp}</td><td>{html.escape(t)}</td></tr>" for kp, t in _AURORA_GUIDE
        ),
    )
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path
