import os

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from health.scan_history import ScanHistory  # noqa: E402
from nas_checker.gui import gui  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat)
    settings.setValue("media_folder", str(tmp_path))
    monkeypatch.setattr(gui, "QSettings", lambda *_: settings)
    monkeypatch.setattr(gui, "ScanHistory", lambda: ScanHistory(str(tmp_path / "history.json")))
    monkeypatch.setattr(gui, "get_storage_profile", lambda *_: {"drive_type": "remote"})
    widget = gui.MainWindow()
    yield widget
    if widget.worker is not None:
        widget.worker.wait(5000)
    app.processEvents()
    widget.close()


def test_unavailable_folder_shows_error_and_restores_controls(window, tmp_path):
    window.media_folder_edit.setText(str(tmp_path / "missing-share"))
    window.start_scan()
    assert window.worker.wait(5000)
    QApplication.processEvents()

    assert "Scan failed" in window.label.text()
    assert "Cannot read media folder" in window.output.toPlainText()
    assert window.start_button.isEnabled()
    assert window.media_folder_edit.isEnabled()
    assert window.browse_folder_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.scan_history.scans() == []


def test_selected_folder_is_used_and_saved(window, tmp_path, monkeypatch):
    selected = str(tmp_path / "different-library")
    window.active_scan_path = str(tmp_path / "old-library")
    window.resume_after = str(tmp_path / "old-library" / "movie.mp4")
    window.media_folder_edit.setText(selected)
    monkeypatch.setattr(gui.ScanWorker, "start", lambda *_: None)
    window.start_scan()

    assert window.worker.path == os.path.normpath(selected)
    assert window.worker.resume_after is None
    assert window.app_settings.value("media_folder") == os.path.normpath(selected)
    assert not window.media_folder_edit.isEnabled()
    assert not window.browse_folder_button.isEnabled()


def test_same_folder_can_resume(window, tmp_path, monkeypatch):
    selected = str(tmp_path)
    marker = str(tmp_path / "movie.mp4")
    window.active_scan_path = selected
    window.resume_after = marker
    monkeypatch.setattr(gui.ScanWorker, "start", lambda *_: None)
    window.start_scan()
    assert window.worker.path == selected
    assert window.worker.resume_after == marker


def test_empty_results_explain_supported_files_without_saving_history(window):
    window.scan_finished({"stats": {"scanned_files": 0}, "bad_files": []})
    assert "No supported media files" in window.label.text()
    assert ".mkv" in window.output.toPlainText()
    assert window.scan_history.scans() == []
    assert not window.stop_button.isEnabled()
