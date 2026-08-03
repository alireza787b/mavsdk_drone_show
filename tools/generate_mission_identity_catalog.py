#!/usr/bin/env python3
"""Generate the dashboard's numeric command identity artifact from Python."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    REPO_ROOT
    / "app/dashboard/drone-dashboard/src/generated/missionIdentities.generated.json"
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.enums import Mission  # noqa: E402


def render_catalog() -> str:
    aliases = [
        key
        for key, mission in Mission.__members__.items()
        if key != mission.name
    ]
    if aliases:
        raise RuntimeError(
            "Mission aliases create a second command identity authority: "
            + ", ".join(aliases)
        )
    identities = [
        {"key": mission.name, "value": mission.value}
        for mission in Mission
    ]
    return json.dumps(identities, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the checked-in generated artifact is stale.",
    )
    args = parser.parse_args()
    rendered = render_catalog()

    if args.check:
        try:
            current = OUTPUT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        if current != rendered:
            print(
                "Mission identity catalog is stale; run "
                "python3 tools/generate_mission_identity_catalog.py",
                file=sys.stderr,
            )
            return 1
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
