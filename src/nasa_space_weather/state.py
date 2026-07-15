from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save(path: Path, data: dict[str, Any]) -> None:
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
