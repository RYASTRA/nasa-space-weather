# ☀️ nasa-space-weather — Space-Weather Watch

A **repo-native, zero-infrastructure** watcher that turns NASA DONKI's space-weather
feed into plain-language **GitHub Issues** — solar flares, Earth-directed CMEs with
predicted arrival windows, and geomagnetic storms with "will I see aurora?" context.

Sibling of [nasa-defense](https://github.com/RYASTRA/nasa-defense) (Planetary-Defense
Watch): same proven engine — GitHub Actions cron → material-delta detection →
idempotent Issues + static Pages status site. No servers, no database, and **no LLM
in the alert path** (deterministic briefings, no hallucination risk).

> **Status: ✅ live — watching DONKI hourly.**
> **Quick look:** <https://ryastra.github.io/nasa-space-weather/>

## The unmet need

DONKI publishes authoritative space-weather events as raw JSON, and forecast
dashboards show *current state* — but nobody turns DONKI's **deltas** into
human-legible alerts: what changed, whether it matters, and what to do about it.

> "CME left the Sun 14:36 UTC; WSA-Enlil predicts arrival Thursday ~03:00 UTC;
> Kp 7 expected — aurora plausible down to ~45° latitude; HF radio degraded dayside."

## What it does

Once per cycle (scheduled GitHub Actions job):

1. **Fetch** solar flares (FLR), CMEs + analyses + WSA-Enlil arrival predictions,
   and geomagnetic storms (GST) from DONKI.
2. **Detect material changes** against the last committed snapshot — routine
   low-class activity is filtered so alerts stay actionable and rare.
3. **Raise idempotent GitHub Issues** in plain English with severity labels;
   events update in place as they evolve (flare → CME → arrival window → storm).
4. **Publish a static status page**: future Earth-arrival forecasts and recently
   passed model times with live countdowns, recent geomagnetic activity,
   high-signal flare context, and an aurora-latitude guide.
5. **Commit the new snapshot** so git history is a tamper-evident ledger.

## Audiences

- **Aurora chasers** — arrival lead time + Kp-to-latitude visibility context
- **Radio amateurs** — flare-class → HF blackout (R-scale) context
- **Satellite operators** — storm heads-up (drag, charging)

## Data source

NASA **DONKI** (Space Weather Database Of Notifications, Knowledge, Information):
`FLR`, `CME`, `CMEAnalysis`, `WSAEnlilSimulations`, `GST` — via `api.nasa.gov`.
Requires `NASA_API_KEY` ([free](https://api.nasa.gov/)), supplied as an Actions secret.

## The RYASTRA fleet

| Repo | What it is |
|---|---|
| [nasa-defense](https://github.com/RYASTRA/nasa-defense) | Planetary-defense watch (the original watcher engine) |
| [nasa-mcp](https://github.com/RYASTRA/nasa-mcp) | All 16 NASA public APIs as an MCP server (R&D layer) |
| [nasa-new-worlds](https://github.com/RYASTRA/nasa-new-worlds) | New-worlds watch — exoplanet confirmations |
| [nasa-observatory](https://github.com/RYASTRA/nasa-observatory) | Fleet dashboard — one tile per watcher |
| [nasa-space-biology](https://github.com/RYASTRA/nasa-space-biology) | Faceted explorer for OSDR space-biology studies |
| **nasa-space-weather** | Space-weather watch *(this repo)* |
| [nasa-tech-explorer](https://github.com/RYASTRA/nasa-tech-explorer) | NASA patents, free software & spinoffs — searchable |

## License

[MIT](LICENSE)
