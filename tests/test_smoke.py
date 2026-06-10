import os
import sys

import pytest


def test_smoke_imports():
    # Keep this test lightweight so CI doesn't require the GUI stack.
    #
    # Pytest can run with a working directory that doesn't automatically put the
    # repo root on `sys.path`, so we force it.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from nas_checker.scan.main import run_scan  # noqa: F401
    from health.hardware import recommend_scan_workers  # noqa: F401
    from health.scan_history import ScanHistory  # noqa: F401
    from health.scan_metadata_cache import ScanMetadataCache  # noqa: F401

    assert callable(run_scan)
    assert callable(recommend_scan_workers)
    assert ScanHistory is not None
    assert ScanMetadataCache is not None


def test_scan_settings_filter_fields_keep_normal_height(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from nas_checker.gui import gui as gui_module

    class DummySignal:
        def connect(self, _callback):
            pass

    class DummyReadSpeedBenchmarkWorker:
        progress = DummySignal()
        finished = DummySignal()

        def __init__(self, _media_folder):
            self.started = False

        def isRunning(self):
            return self.started

        def start(self):
            self.started = True

    monkeypatch.setattr(gui_module, "run_preflight_checks", lambda require_ffmpeg: [])
    monkeypatch.setattr(
        gui_module.MainWindow, "_check_overdue_scan_prompt", lambda self: None
    )
    monkeypatch.setattr(gui_module, "get_storage_profile", lambda _path: {})
    monkeypatch.setattr(
        gui_module, "ReadSpeedBenchmarkWorker", DummyReadSpeedBenchmarkWorker
    )

    app = QApplication.instance() or QApplication([])
    window = gui_module.MainWindow(media_folder=str(tmp_path))
    settings_tab_index = next(
        i
        for i in range(window.tabs.count())
        if window.tabs.tabText(i) == "Scan Settings"
    )
    window.tabs.setCurrentWidget(window.tabs.widget(settings_tab_index))
    window.resize(1000, 800)
    window.show()
    window.layout().activate()
    app.processEvents()

    assert window.minimumSize().height() <= 750

    container_height = window.scan_rules_containers_edit.height()
    peer_heights = [
        window.scan_rules_video_codecs_edit.height(),
        window.scan_rules_audio_codecs_edit.height(),
    ]

    assert container_height >= 20
    assert container_height >= min(peer_heights) - 2

    def rect_in_window(widget):
        return widget.geometry().translated(
            widget.parentWidget().mapTo(window, QPoint(0, 0))
        )

    assert not rect_in_window(window.read_speed_test_button).intersects(
        rect_in_window(window.scan_rules_containers_edit)
    )

    window.read_speed_test_button.click()
    app.processEvents()

    assert not window.scan_rules_containers_edit.hasFocus()

    window.close()


def test_gui_start_scan_uses_visible_path_and_clears_stale_resume(
    tmp_path, monkeypatch
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from PySide6.QtWidgets import QApplication

    from nas_checker.gui import gui as gui_module
    from nas_checker.scan.scan_path_settings import load_scan_path_settings

    class DummySignal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

    class DummyScanWorker:
        def __init__(self, path, resume_after=None, max_workers=None):
            self.path = path
            self.resume_after = resume_after
            self.max_workers = max_workers
            self.progress = DummySignal()
            self.log = DummySignal()
            self.issue = DummySignal()
            self.finished = DummySignal()
            self.started = False

        def isRunning(self):
            return self.started

        def start(self):
            self.started = True

    monkeypatch.setattr(gui_module, "run_preflight_checks", lambda require_ffmpeg: [])
    monkeypatch.setattr(
        gui_module.MainWindow, "_check_overdue_scan_prompt", lambda self: None
    )
    monkeypatch.setattr(gui_module, "get_storage_profile", lambda _path: {})
    monkeypatch.setattr(gui_module, "ScanWorker", DummyScanWorker)

    app = QApplication.instance() or QApplication([])
    window = gui_module.MainWindow(media_folder=str(tmp_path / "Shows"))
    settings_path = tmp_path / "scan_path_settings.json"
    window.scan_path_settings_path = str(settings_path)

    media_root = tmp_path / "Media"
    previous_show = tmp_path / "Shows" / "Show" / "Season 01" / "episode.mkv"
    window.scan_media_folder_edit.setText(str(media_root))
    window.resume_after = str(previous_show)
    window.resume_scan_root = os.path.normpath(str(tmp_path / "Shows"))

    window.start_scan()
    app.processEvents()

    assert window.worker.path == os.path.normpath(str(media_root))
    assert window.worker.resume_after is None
    assert window.resume_after is None
    assert load_scan_path_settings(str(settings_path))[
        "media_folder"
    ] == os.path.normpath(str(media_root))
    assert "Scan root changed since the stopped scan" in window.output.toPlainText()

    window.close()
