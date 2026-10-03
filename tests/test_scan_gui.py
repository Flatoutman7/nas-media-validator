import os

import pytest


pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from health.scan_history import ScanHistory  # noqa: E402
from nas_checker.gui import gui  # noqa: E402
from nas_checker.scan.scan_path_settings import load_scan_path_settings  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "ScanHistory", lambda: ScanHistory(str(tmp_path / "history.json")))
    monkeypatch.setattr(gui, "get_default_scan_path_settings_path", lambda: str(tmp_path / "paths.json"))
    monkeypatch.setattr(gui, "get_default_arr_config_path", lambda: str(tmp_path / "arr.json"))
    monkeypatch.setattr(gui, "get_storage_profile", lambda *_: {"drive_type": "remote"})
    monkeypatch.setattr(gui, "get_scan_worker_recommendation", lambda *_: {"workers": 1})
    monkeypatch.setattr(gui, "run_preflight_checks", lambda **_: [])
    monkeypatch.setattr("nas_checker.scan.main.run_preflight_checks", lambda **_: [])
    monkeypatch.setattr(gui.MainWindow, "_check_overdue_scan_prompt", lambda self: None)
    widget = gui.MainWindow(media_folder=str(tmp_path))
    widget.scan_workers_auto_checkbox.setChecked(False)
    widget.scan_workers_manual_spin.setValue(1)
    yield widget
    if widget.worker is not None:
        widget.worker.wait(5000)
    app.processEvents()
    widget.close()


def test_unavailable_folder_shows_error_and_restores_controls(window, tmp_path):
    window.scan_media_folder_edit.setText(str(tmp_path / "missing-share"))
    window.start_scan()
    assert window.worker.wait(5000)
    QApplication.processEvents()

    assert "Scan failed" in window.label.text()
    assert "missing-share" in window.output.toPlainText()
    assert window.start_button.isEnabled()
    assert window.scan_media_folder_edit.isEnabled()
    assert window.scan_media_folder_browse_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.scan_history.scans() == []


def test_selected_folder_is_used_and_saved(window, tmp_path, monkeypatch):
    selected = str(tmp_path / "different-library")
    window.resume_scan_root = str(tmp_path / "old-library")
    window.resume_after = str(tmp_path / "old-library" / "movie.mp4")
    window.scan_media_folder_edit.setText(selected)
    monkeypatch.setattr(window, "_start_worker", lambda *_: None)
    window.start_scan()

    assert window.worker.path == os.path.normpath(selected)
    assert window.worker.resume_after is None
    assert load_scan_path_settings(window.scan_path_settings_path)["media_folder"] == os.path.normpath(selected)
    assert not window.scan_media_folder_edit.isEnabled()
    assert not window.scan_media_folder_browse_button.isEnabled()


def test_same_folder_can_resume(window, tmp_path, monkeypatch):
    selected = str(tmp_path)
    marker = str(tmp_path / "movie.mp4")
    window.resume_scan_root = selected
    window.resume_after = marker
    monkeypatch.setattr(window, "_start_worker", lambda *_: None)
    window.start_scan()
    assert window.worker.path == selected
    assert window.worker.resume_after == marker


def test_empty_results_explain_supported_files_without_saving_history(window):
    window.scan_finished({"stats": {"scanned_files": 0}, "bad_files": []})
    assert "No supported media files" in window.label.text()
    assert ".mkv" in window.output.toPlainText()
    assert window.scan_history.scans() == []
    assert not window.stop_button.isEnabled()


def test_completed_scan_records_selected_folder(window):
    window.scan_finished({"stats": {"scanned_files": 1}, "bad_files": []})
    assert window.scan_history.scans()[0]["media_folder"] == window.media_folder
    assert window.scan_media_folder_edit.isEnabled()
    assert window.scan_media_folder_browse_button.isEnabled()
