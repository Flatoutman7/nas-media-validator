import json
import os
from typing import Any

DEFAULT_MEDIA_FOLDER = "Z:/"
SCAN_PATH_ENV_VAR = "NAS_SCAN_PATH"
DEFAULT_AUTO_WORKERS = True
DEFAULT_MANUAL_WORKERS = 4
AUTO_FIX_MODE_OFF = "off"
AUTO_FIX_MODE_PROMPT = "prompt"
AUTO_FIX_MODE_AUTO_RUN = "auto_run"
DEFAULT_AUTO_FIX_MODE = AUTO_FIX_MODE_OFF
AUTO_FIX_MODES = {
    AUTO_FIX_MODE_OFF,
    AUTO_FIX_MODE_PROMPT,
    AUTO_FIX_MODE_AUTO_RUN,
}
MEASURED_READ_MB_S_KEY = "measured_read_mb_s"
EFFECTIVE_READ_MB_S_KEY = "effective_read_mb_s"
RAW_MEASURED_READ_MB_S_KEY = "raw_measured_read_mb_s"
MEASURED_READ_CONFIDENCE_KEY = "measured_read_confidence"
MEASURED_READ_AT_KEY = "measured_read_at"


def normalize_scan_path(path: str | None) -> str:
    if not path or not str(path).strip():
        return DEFAULT_MEDIA_FOLDER
    normalized = os.path.normpath(str(path).strip())
    if not normalized:
        return DEFAULT_MEDIA_FOLDER
    return normalized


def get_default_scan_path_settings_path() -> str:
    gui_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(gui_dir, "gui", "scan_path_settings.json")


def normalize_auto_fix_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in AUTO_FIX_MODES else DEFAULT_AUTO_FIX_MODE


def load_scan_path_settings(path: str | None = None) -> dict[str, Any]:
    if not path:
        path = get_default_scan_path_settings_path()
    defaults = {
        "media_folder": DEFAULT_MEDIA_FOLDER,
        "auto_workers": DEFAULT_AUTO_WORKERS,
        "manual_workers": DEFAULT_MANUAL_WORKERS,
        "auto_fix_mode": DEFAULT_AUTO_FIX_MODE,
        MEASURED_READ_MB_S_KEY: None,
        EFFECTIVE_READ_MB_S_KEY: None,
        RAW_MEASURED_READ_MB_S_KEY: None,
        MEASURED_READ_CONFIDENCE_KEY: None,
        MEASURED_READ_AT_KEY: None,
    }
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                defaults.update(loaded)
    except Exception:
        pass

    defaults["media_folder"] = normalize_scan_path(defaults.get("media_folder"))
    defaults["auto_workers"] = bool(defaults.get("auto_workers", DEFAULT_AUTO_WORKERS))
    defaults["auto_fix_mode"] = normalize_auto_fix_mode(defaults.get("auto_fix_mode"))
    try:
        manual_workers = int(defaults.get("manual_workers", DEFAULT_MANUAL_WORKERS))
    except Exception:
        manual_workers = DEFAULT_MANUAL_WORKERS
    defaults["manual_workers"] = max(1, min(64, manual_workers))
    measured_read = defaults.get(MEASURED_READ_MB_S_KEY)
    try:
        measured_read_value = float(measured_read)
    except Exception:
        measured_read_value = 0.0
    defaults[MEASURED_READ_MB_S_KEY] = (
        measured_read_value if measured_read_value > 0 else None
    )
    for key in (EFFECTIVE_READ_MB_S_KEY, RAW_MEASURED_READ_MB_S_KEY):
        value = defaults.get(key)
        try:
            numeric_value = float(value)
        except Exception:
            numeric_value = 0.0
        defaults[key] = numeric_value if numeric_value > 0 else None
    confidence = defaults.get(MEASURED_READ_CONFIDENCE_KEY)
    defaults[MEASURED_READ_CONFIDENCE_KEY] = str(confidence) if confidence else None
    measured_at = defaults.get(MEASURED_READ_AT_KEY)
    defaults[MEASURED_READ_AT_KEY] = str(measured_at) if measured_at else None
    return defaults


def save_scan_path_settings(settings: dict[str, Any], path: str | None = None) -> None:
    if not path:
        path = get_default_scan_path_settings_path()
    folder = normalize_scan_path(settings.get("media_folder"))
    current = load_scan_path_settings(path)
    payload = dict(current)
    payload["media_folder"] = folder
    if "auto_workers" in settings:
        payload["auto_workers"] = bool(settings.get("auto_workers"))
    if "manual_workers" in settings:
        try:
            manual_workers = int(settings.get("manual_workers"))
        except Exception:
            manual_workers = DEFAULT_MANUAL_WORKERS
        payload["manual_workers"] = max(1, min(64, manual_workers))
    if "auto_fix_mode" in settings:
        payload["auto_fix_mode"] = normalize_auto_fix_mode(
            settings.get("auto_fix_mode")
        )
    if MEASURED_READ_MB_S_KEY in settings:
        measured_read = settings.get(MEASURED_READ_MB_S_KEY)
        try:
            measured_read_value = float(measured_read)
        except Exception:
            measured_read_value = 0.0
        payload[MEASURED_READ_MB_S_KEY] = (
            measured_read_value if measured_read_value > 0 else None
        )
    for key in (EFFECTIVE_READ_MB_S_KEY, RAW_MEASURED_READ_MB_S_KEY):
        if key in settings:
            value = settings.get(key)
            try:
                numeric_value = float(value)
            except Exception:
                numeric_value = 0.0
            payload[key] = numeric_value if numeric_value > 0 else None
    if MEASURED_READ_CONFIDENCE_KEY in settings:
        confidence = settings.get(MEASURED_READ_CONFIDENCE_KEY)
        payload[MEASURED_READ_CONFIDENCE_KEY] = str(confidence) if confidence else None
    if MEASURED_READ_AT_KEY in settings:
        measured_at = settings.get(MEASURED_READ_AT_KEY)
        payload[MEASURED_READ_AT_KEY] = str(measured_at) if measured_at else None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def parse_cli_scan_path(argv: list[str] | None = None) -> str | None:
    if argv is None:
        import sys

        argv = sys.argv
    try:
        from nas_checker.cli import parse_args

        args = parse_args(argv[1:] if argv and argv[0].endswith(".py") else argv)
        return args.path
    except SystemExit:
        pass
    for i, arg in enumerate(argv):
        if arg in ("--path", "-p") and i + 1 < len(argv):
            value = argv[i + 1]
            if value and not value.startswith("-"):
                return value
    return None


def resolve_scan_path(cli_path: str | None = None) -> str:
    if cli_path:
        return normalize_scan_path(cli_path)

    env_path = os.environ.get(SCAN_PATH_ENV_VAR)
    if env_path:
        return normalize_scan_path(env_path)

    settings = load_scan_path_settings()
    return normalize_scan_path(settings.get("media_folder"))
