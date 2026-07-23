"""Tunable thresholds, DONKI endpoints, and filesystem paths resolved from the environment."""

from __future__ import annotations

import os
from pathlib import Path

# --- Materiality: solar flares (FLR) ---
# Flare class letter ranks A < B < C < M < X. A/B/C are near-daily noise and are suppressed
# on their own; they surface only as `info` context inside a live episode, or as a swarm.
FLARE_ALERT_MIN_CLASS = "M"  # M and X earn an alert on their own
FLARE_CRITICAL_CLASS = "X"

# --- Materiality: flare swarms ---
# An active region firing repeatedly is a real precursor signal even when no single flare is
# large. This is the "multiple small things add up" rule. It sets a FLOOR of `high` — it must
# never reach `critical` on its own, or every routine active region would scream.
FLARE_SWARM_MIN_CLASS = "C"
FLARE_SWARM_COUNT = 5
FLARE_SWARM_WINDOW_H = 24

# --- Materiality: CMEs ---
CME_FAST_KMS = 800.0  # at/above this speed, an Earth-directed CME is critical

# --- Materiality: geomagnetic storms (GST) ---
GST_ALERT_MIN_KP = 5.0  # G1 — aurora becomes visible at high latitudes
GST_CRITICAL_KP = 7.0  # G3 — aurora reaches ~45 deg; satellite drag/charging

# --- Fetch window ---
FETCH_LOOKBACK_DAYS = 30  # DONKI's own default, and its maximum range

# --- Relevance window (forward-looking) ---
# This is a FORECAST/nowcast: alert only on what's incoming or recent. An event qualifies if its
# effects are still ahead of us (a predicted CME arrival in the FUTURE) or within this many hours
# in the past (a storm/flare that just happened). Anything older — effects already over — is
# ignored. Future timestamps always pass; this bound only governs how far back "recent" reaches.
RELEVANCE_WINDOW_H = 72

# --- HTTP ---
# Retries must span enough wall clock to OUTLAST an upstream gateway blip — that is what
# defeats them, not the attempt count. Equal-jitter backoff over 5 attempts spans 7.5-15s.
# Every DONKI source is on api.nasa.gov, which DOES rate-limit, so the 429 branch in
# sources/http.py is load-bearing here, not a nicety.
HTTP_TIMEOUT_S = 30.0
HTTP_RETRIES = 5
HTTP_BACKOFF_BASE_S = 1.0
HTTP_BACKOFF_CAP_S = 10.0

# --- Source health ---
# A source that is briefly unreachable is expected and self-healing: its state is not
# advanced, so the next run re-detects whatever was missed. Only escalate to a hard failure
# once a source has been down this many consecutive runs, at which point we may genuinely be
# blind to something rather than just waiting out an outage.
SOURCE_FAILURE_LIMIT = 3

# --- Output ---
SITE_ENABLED = True

# --- Endpoints (ALL on api.nasa.gov: one host, one key, one quota — they fail together) ---
DONKI_ROOT = "https://api.nasa.gov/DONKI"
FLR_API = f"{DONKI_ROOT}/FLR"
CME_API = f"{DONKI_ROOT}/CME"
GST_API = f"{DONKI_ROOT}/GST"

# --- Paths ---
STATE_DIR = Path(os.environ.get("NASA_SPACE_WEATHER_STATE_DIR", "state"))
SITE_DIR = Path(os.environ.get("NASA_SPACE_WEATHER_SITE_DIR", "site"))

SCHEMA_VERSION = 1


def nasa_api_key() -> str:
    """Return the NASA API key from the environment.

    Raises:
        RuntimeError: when NASA_API_KEY is unset, naming the places it can be set.
    """
    key = os.environ.get("NASA_API_KEY")
    if not key:
        raise RuntimeError(
            "NASA_API_KEY is not set — add it to .env (see .env.example) or set it "
            "in the environment / GitHub Actions secrets."
        )
    return key


def load_dotenv(path: Path | str = ".env") -> None:
    """Load `KEY=VALUE` lines from a local .env into the environment for keys not already
    set (real env vars / CI secrets always win). Convenience for local runs; a no-op when
    the file is absent."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
