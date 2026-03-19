import hashlib
import json
import os
from typing import Any


DEFAULT_SCAN_RULES_SETTINGS: dict[str, Any] = {
    # Extensions without the leading dot.
    "containers": ["mp4"],
    "video_codecs": ["hevc"],
    "audio_codecs": ["aac"],
}


def _normalize_list_csv(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip().lower()
        if not s:
            continue
        if s.startswith("."):
            s = s[1:]
        out.append(s)
    # stable unique
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def normalize_scan_rules_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_SCAN_RULES_SETTINGS)
    if not isinstance(settings, dict):
        return merged

    containers = _normalize_list_csv(settings.get("containers"))
    video_codecs = _normalize_list_csv(settings.get("video_codecs"))
    audio_codecs = _normalize_list_csv(settings.get("audio_codecs"))

    if containers:
        merged["containers"] = containers
    if video_codecs:
        merged["video_codecs"] = video_codecs
    if audio_codecs:
        merged["audio_codecs"] = audio_codecs
    return merged


def compute_scan_rules_hash(settings: dict[str, Any]) -> str:
    normalized = normalize_scan_rules_settings(settings)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def get_default_scan_rules_settings_path() -> str:
    # Persist next to the GUI so a user can edit it easily.
    # Note: rules also have defaults when this file doesn't exist.
    gui_dir = os.path.dirname(os.path.dirname(__file__))  # nas_checker/
    # We want nas_checker/gui/scan_rules_settings.json.
    return os.path.join(gui_dir, "gui", "scan_rules_settings.json")


def load_scan_rules_settings(path: str | None = None) -> dict[str, Any]:
    if not path:
        path = get_default_scan_rules_settings_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return normalize_scan_rules_settings(loaded)
    except Exception:
        pass
    return dict(DEFAULT_SCAN_RULES_SETTINGS)


def save_scan_rules_settings(settings: dict[str, Any], path: str | None = None) -> None:
    if not path:
        path = get_default_scan_rules_settings_path()
    normalized = normalize_scan_rules_settings(settings)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)
    except Exception:
        # Best-effort; don't crash the app if disk is read-only.
        pass

