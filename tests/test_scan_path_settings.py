import os

from nas_checker.scan.scan_path_settings import (
    AUTO_FIX_MODE_AUTO_RUN,
    AUTO_FIX_MODE_OFF,
    AUTO_FIX_MODE_PROMPT,
    DEFAULT_MANUAL_WORKERS,
    EFFECTIVE_READ_MB_S_KEY,
    MEASURED_READ_CONFIDENCE_KEY,
    load_scan_path_settings,
    RAW_MEASURED_READ_MB_S_KEY,
    resolve_scan_path,
    save_scan_path_settings,
)


def test_scan_path_settings_persist_measured_read_speed(tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"

    save_scan_path_settings(
        {
            "media_folder": "Z:/Media",
            "auto_workers": False,
            "manual_workers": 9,
            "measured_read_mb_s": 123.4,
            EFFECTIVE_READ_MB_S_KEY: 123.4,
            RAW_MEASURED_READ_MB_S_KEY: 4100.0,
            MEASURED_READ_CONFIDENCE_KEY: "low",
            "measured_read_at": "2026-06-10T15:00:00Z",
        },
        str(settings_path),
    )

    loaded = load_scan_path_settings(str(settings_path))

    assert loaded["media_folder"] == os.path.normpath("Z:/Media")
    assert loaded["auto_workers"] is False
    assert loaded["manual_workers"] == 9
    assert loaded["auto_fix_mode"] == AUTO_FIX_MODE_OFF
    assert loaded["measured_read_mb_s"] == 123.4
    assert loaded[EFFECTIVE_READ_MB_S_KEY] == 123.4
    assert loaded[RAW_MEASURED_READ_MB_S_KEY] == 4100.0
    assert loaded[MEASURED_READ_CONFIDENCE_KEY] == "low"
    assert loaded["measured_read_at"] == "2026-06-10T15:00:00Z"


def test_scan_path_settings_preserve_measured_speed_on_worker_save(tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"
    save_scan_path_settings(
        {
            "media_folder": "Z:/Media",
            "measured_read_mb_s": 88.0,
            EFFECTIVE_READ_MB_S_KEY: 88.0,
            RAW_MEASURED_READ_MB_S_KEY: 88.0,
            MEASURED_READ_CONFIDENCE_KEY: "normal",
            "measured_read_at": "2026-06-10T15:00:00Z",
        },
        str(settings_path),
    )

    save_scan_path_settings({"manual_workers": 6}, str(settings_path))
    loaded = load_scan_path_settings(str(settings_path))

    assert loaded["manual_workers"] == 6
    assert loaded["measured_read_mb_s"] == 88.0
    assert loaded[EFFECTIVE_READ_MB_S_KEY] == 88.0
    assert loaded[RAW_MEASURED_READ_MB_S_KEY] == 88.0
    assert loaded[MEASURED_READ_CONFIDENCE_KEY] == "normal"
    assert loaded["measured_read_at"] == "2026-06-10T15:00:00Z"


def test_scan_path_settings_invalid_measured_speed_is_ignored(tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"
    settings_path.write_text(
        '{"manual_workers": "bad", "measured_read_mb_s": "bad"}',
        encoding="utf-8",
    )

    loaded = load_scan_path_settings(str(settings_path))

    assert loaded["manual_workers"] == DEFAULT_MANUAL_WORKERS
    assert loaded["measured_read_mb_s"] is None
    assert loaded[EFFECTIVE_READ_MB_S_KEY] is None
    assert loaded[RAW_MEASURED_READ_MB_S_KEY] is None


def test_scan_path_settings_persist_auto_fix_mode(tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"

    save_scan_path_settings(
        {"media_folder": "Z:/Media", "auto_fix_mode": AUTO_FIX_MODE_PROMPT},
        str(settings_path),
    )
    loaded = load_scan_path_settings(str(settings_path))

    assert loaded["auto_fix_mode"] == AUTO_FIX_MODE_PROMPT

    save_scan_path_settings(
        {"media_folder": "Z:/Media", "auto_fix_mode": AUTO_FIX_MODE_AUTO_RUN},
        str(settings_path),
    )
    loaded = load_scan_path_settings(str(settings_path))

    assert loaded["auto_fix_mode"] == AUTO_FIX_MODE_AUTO_RUN


def test_scan_path_settings_invalid_auto_fix_mode_defaults_off(tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"
    settings_path.write_text('{"auto_fix_mode": "danger"}', encoding="utf-8")

    loaded = load_scan_path_settings(str(settings_path))

    assert loaded["auto_fix_mode"] == AUTO_FIX_MODE_OFF


def test_resolve_scan_path_prefers_cli_path(monkeypatch, tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"
    save_scan_path_settings({"media_folder": "Z:/Shows"}, str(settings_path))
    monkeypatch.setenv("NAS_SCAN_PATH", "Z:/TV")
    monkeypatch.setattr(
        "nas_checker.scan.scan_path_settings.get_default_scan_path_settings_path",
        lambda: str(settings_path),
    )

    assert resolve_scan_path(cli_path="Z:/Media") == os.path.normpath("Z:/Media")


def test_resolve_scan_path_prefers_env_over_saved_settings(monkeypatch, tmp_path):
    settings_path = tmp_path / "scan_path_settings.json"
    save_scan_path_settings({"media_folder": "Z:/Shows"}, str(settings_path))
    monkeypatch.setenv("NAS_SCAN_PATH", "Z:/Media")
    monkeypatch.setattr(
        "nas_checker.scan.scan_path_settings.get_default_scan_path_settings_path",
        lambda: str(settings_path),
    )

    assert resolve_scan_path() == os.path.normpath("Z:/Media")
