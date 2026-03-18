import json
import os
import sys
from typing import Any


def load_arr_config(config_path: str | None = None) -> dict[str, Any] | None:
    """
    Load Sonarr/Radarr connection info from a local JSON file.

    This file is intentionally gitignored to avoid committing API keys.
    """

    candidates: list[str] = []
    if config_path:
        candidates.append(config_path)
    else:
        # 1) Same folder as this module (works in dev).
        candidates.append(os.path.join(os.path.dirname(__file__), "arr_config.json"))

        # 2) Next to the executable (works in packaged mode when user copies config).
        exe_path = sys.argv[0] or sys.executable
        exe_dir = os.path.dirname(os.path.abspath(exe_path)) if exe_path else None
        if exe_dir:
            candidates.append(os.path.join(exe_dir, "arr_config.json"))

            # 3) One folder up from `dist/` when running from PyInstaller output.
            candidates.append(os.path.join(exe_dir, "..", "arr_config.json"))

        # 4) Current working directory.
        candidates.append(os.path.join(os.getcwd(), "arr_config.json"))

    resolved = None
    for c in candidates:
        if c and os.path.exists(c):
            resolved = c
            break

    if not resolved:
        return None

    with open(resolved, "r", encoding="utf-8") as f:
        return json.load(f)
