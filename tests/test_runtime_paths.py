import os
import sys

from health.scan_history import ScanHistory
from nas_checker.arr.arr_config import get_default_arr_config_path
from nas_checker.runtime_paths import persistent_data_path
from nas_checker.scan.scan_path_settings import load_scan_path_settings, save_scan_path_settings
from nas_checker.scan.scan_rules_settings import get_default_scan_rules_settings_path


def test_source_data_paths_stay_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    source = str(tmp_path / "settings.json")
    assert persistent_data_path(source) == source


def test_packaged_paths_survive_different_extraction_folders(tmp_path, monkeypatch):
    executable = tmp_path / "release" / "NAS Checker.exe"
    executable.parent.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    first = persistent_data_path(str(tmp_path / "_MEI_first" / "settings.json"))
    second = persistent_data_path(str(tmp_path / "_MEI_second" / "settings.json"))
    assert first == second == str(executable.parent / "data" / "settings.json")


def test_packaged_history_and_settings_persist_on_reopen(tmp_path, monkeypatch):
    executable = tmp_path / "NAS Checker.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    saved_path = str(tmp_path / "Media Library")
    save_scan_path_settings({"media_folder": saved_path})
    ScanHistory().add_scan({"stats": {"scanned_files": 3}, "bad_files": []})
    assert load_scan_path_settings()["media_folder"] == os.path.normpath(saved_path)
    assert ScanHistory().scans()[0]["stats"]["scanned_files"] == 3
    assert get_default_arr_config_path() == str(tmp_path / "data" / "arr_config.json")
    assert get_default_scan_rules_settings_path() == str(tmp_path / "data" / "scan_rules_settings.json")
