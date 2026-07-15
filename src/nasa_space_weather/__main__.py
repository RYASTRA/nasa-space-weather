from __future__ import annotations

import argparse
import sys

from . import config, watch


def main() -> int:
    parser = argparse.ArgumentParser(prog="nasa_space_weather")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and detect, but write nothing: no Issues, no state, no site. "
        "Safe to point at the live API.",
    )
    args = parser.parse_args()

    config.load_dotenv()
    try:
        episodes_found = watch.run(dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"::error::{exc}")  # STDOUT — Actions reads workflow commands from stdout
        return 1
    print(f"{len(episodes_found)} actionable episode(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
