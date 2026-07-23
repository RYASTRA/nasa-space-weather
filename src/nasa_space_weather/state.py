"""Atomic JSON persistence for per-source detection snapshots."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    """Read the JSON state at `path`, or an empty dict if it has not been written yet."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save(path: Path, data: dict[str, Any]) -> None:
    """Write `data` to `path` as sorted JSON, atomically.

    Uses a temp file plus `os.replace` so a process killed mid-write leaves the previous
    snapshot intact rather than a truncated one. A corrupt state file would make the next
    run re-announce everything it had already reported.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    # Atomic write: temp file + rename, so a process kill mid-write can never leave
    # a half-written (corrupt) snapshot — the previous file stays intact until the
    # os.replace succeeds.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
