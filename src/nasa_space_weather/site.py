from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import Any

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
  body {{ font-family: system-ui, sans-serif; max-width: 46rem; margin: 2rem auto;
          padding: 0 1rem; line-height: 1.5; }}
  .sev-critical {{ border-left: 4px solid #b00; padding-left: .75rem; }}
  .sev-high {{ border-left: 4px solid #d80; padding-left: .75rem; }}
  .sev-info {{ border-left: 4px solid #999; padding-left: .75rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td, th {{ text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #ddd; }}
  footer {{ margin-top: 3rem; color: #666; font-size: .85rem; }}
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


def _arrivals(episodes: list[Episode], events: dict[str, Any]) -> str:
    rows: list[str] = []
    for episode in episodes:
        for member in episode.members:
            event = events.get(member.activity_id)
            if not isinstance(event, CME):
                continue
            if not event.has_analysis or event.enlil is None or event.enlil.arrival_time is None:
                # SILENCE READS AS SAFE — never just drop the row.
                rows.append(
                    f'<li class="sev-{html.escape(episode.severity)}">CME '
                    f"{html.escape(_stamp(event.start_time))} — "
                    f"<strong>arrival prediction not yet available</strong></li>"
                )
                continue
            arrival = event.enlil.arrival_time
            kp = event.enlil.predicted_kp
            kp_text = f" — predicted Kp {kp:.0f}. {aurora_latitude(kp)}" if kp else ""
            rows.append(
                f'<li class="sev-{html.escape(episode.severity)}" '
                f'data-arrival="{arrival.isoformat()}">'
                f"<strong>Arrives {html.escape(_stamp(arrival))}</strong>"
                f"{html.escape(kp_text)}</li>"
            )
    return f"<ul>{''.join(rows)}</ul>" if rows else "<p>Nothing inbound.</p>"


def _conditions(episodes: list[Episode], events: dict[str, Any]) -> str:
    storms = [
        events[m.activity_id]
        for ep in episodes
        for m in ep.members
        if isinstance(events.get(m.activity_id), Storm)
    ]
    active = [s for s in storms if s.max_kp is not None]
    if not active:
        return "<p>Geomagnetically quiet.</p>"
    worst = max(active, key=lambda s: s.max_kp or 0)
    return (
        f"<p><strong>Kp {worst.max_kp:.0f}</strong> — "
        f"{html.escape(aurora_latitude(worst.max_kp))}</p>"
    )


def render_site(episodes: list[Episode], events: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    page = _PAGE.format(
        generated=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        arrivals=_arrivals(episodes, events),
        conditions=_conditions(episodes, events),
        aurora_rows="".join(
            f"<tr><td>{kp}</td><td>{html.escape(t)}</td></tr>" for kp, t in _AURORA_GUIDE
        ),
    )
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path
