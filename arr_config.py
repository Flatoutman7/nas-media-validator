import json
import os
from typing import Any


def load_arr_config(config_path: str | None = None) -> dict[str, Any] | None:
    """
    Load Sonarr/Radarr connection info from a local JSON file.

    This file is intentionally gitignored to avoid committing API keys.
    """

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(__file__),
            "arr_config.json",
        )

    if not os.path.exists(config_path):
        return None

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
