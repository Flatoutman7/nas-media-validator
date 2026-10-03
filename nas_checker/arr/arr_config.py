import json
import os
import sys
from typing import Any
from urllib.parse import urlparse

ARR_SERVICES = ("sonarr", "radarr")


def get_default_arr_config_path() -> str:
    return os.path.join(os.path.dirname(__file__), "arr_config.json")


def normalize_arr_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    normalized: dict[str, Any] = {}

    for service in ARR_SERVICES:
        service_config = config.get(service)
        if not isinstance(service_config, dict):
            service_config = {}

        normalized[service] = {
            "enabled": bool(service_config.get("enabled", False)),
            "base_url": str(service_config.get("base_url") or "").strip().rstrip("/"),
            "api_key": str(service_config.get("api_key") or "").strip(),
        }

    return normalized


def validate_arr_service_config(
    service: str,
    service_config: dict[str, Any] | None,
) -> list[str]:
    label = service.capitalize()
    if not isinstance(service_config, dict):
        return [f"{label} is not configured."]

    if service_config.get("enabled") is False:
        return [f"{label} is disabled."]

    base_url = str(service_config.get("base_url") or "").strip()
    api_key = str(service_config.get("api_key") or "").strip()
    errors = []

    if not base_url:
        errors.append(f"{label} base URL is required.")
    else:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{label} base URL must start with http:// or https://.")

    if not api_key:
        errors.append(f"{label} API key is required.")

    return errors


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
        candidates.append(get_default_arr_config_path())

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
        return normalize_arr_config(json.load(f))


def save_arr_config(config: dict[str, Any], config_path: str | None = None) -> str:
    resolved = config_path or get_default_arr_config_path()
    config_dir = os.path.dirname(resolved)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    normalized = normalize_arr_config(config)

    with open(resolved, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2)
        f.write("\n")

    return resolved
