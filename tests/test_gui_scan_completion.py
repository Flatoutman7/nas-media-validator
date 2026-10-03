import os
from datetime import datetime, timezone

import pytest

from health.scan_history import ScanHistory
from nas_checker.scan.issues import ISSUE_NO_AUDIO, ISSUE_NO_VIDEO, make_issue


def _create_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from nas_checker.gui import gui as gui_module

    monkeypatch.setattr(gui_module, "run_preflight_checks", lambda require_ffmpeg: [])
    monkeypatch.setattr(
        gui_module.MainWindow, "_check_overdue_scan_prompt", lambda self: None
    )
    monkeypatch.setattr(gui_module, "get_storage_profile", lambda _path: {})

    app = QApplication.instance() or QApplication([])
    window = gui_module.MainWindow(media_folder=str(tmp_path))
    window.scan_history = ScanHistory(str(tmp_path / "scan_history.json"))
    window.current_scan_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return app, window


def test_scan_finished_persists_structured_payload_without_table_snapshot(
    tmp_path, monkeypatch
):
    _app, window = _create_window(tmp_path, monkeypatch)
    window.library_stats_total = window._empty_library_stats_total()

    def fail_table_snapshot():
        raise AssertionError("scan completion should not parse the UI table")

    window._get_table_bad_files_snapshot = fail_table_snapshot

    window.scan_finished(
        {
            "cancelled": False,
            "bad_files": [
                (
                    r"Z:\Movies\bad.mkv",
                    [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
                )
            ],
            "stats": {"scanned_files": 1, "files_with_issues": 1},
        }
    )

    records = window.scan_history.scans()
    assert len(records) == 1
    assert records[0]["bad_files"] == [
        {
            "file": os.path.normpath(r"Z:\Movies\bad.mkv"),
            "issues": [{"code": ISSUE_NO_AUDIO, "message": "No audio stream found"}],
        }
    ]
    assert records[0]["issues_total"] == 1
    assert r"Z:\Movies\bad.mkv" not in window.output.toPlainText()

    window.close()


def test_resumed_scan_history_uses_accumulated_issue_model(tmp_path, monkeypatch):
    _app, window = _create_window(tmp_path, monkeypatch)
    window.library_stats_total = window._empty_library_stats_total()
    window._current_scan_is_resume = True
    window._reset_current_scan_bad_files_model()
    window._record_current_scan_issue(
        r"Z:\Shows\old.mkv",
        make_issue(ISSUE_NO_VIDEO, "No video stream found"),
    )

    window.scan_finished(
        {
            "cancelled": False,
            "bad_files": [
                (
                    r"Z:\Shows\new.mkv",
                    [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
                )
            ],
            "stats": {"scanned_files": 2, "files_with_issues": 2},
        }
    )

    record = window.scan_history.scans()[0]
    files = {entry["file"] for entry in record["bad_files"]}

    assert files == {
        os.path.normpath(r"Z:\Shows\old.mkv"),
        os.path.normpath(r"Z:\Shows\new.mkv"),
    }
    assert record["issues_total"] == 2

    window.close()


def test_cancelled_scan_does_not_start_auto_fix(tmp_path, monkeypatch):
    _app, window = _create_window(tmp_path, monkeypatch)

    def fail_auto_fix_after_scan():
        raise AssertionError("cancelled scans must not start auto-fix")

    window._handle_auto_fix_after_scan = fail_auto_fix_after_scan
    window.scan_finished(
        {
            "cancelled": True,
            "resume_after": r"Z:\Shows\later.mkv",
            "bad_files": [
                (
                    r"Z:\Shows\bad.mkv",
                    [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
                )
            ],
            "stats": {"scanned_files": 1, "files_with_issues": 1},
        }
    )

    assert window.label.text() == "Stopped — ready to resume"

    window.close()


def test_scan_failure_restores_controls_without_history_or_auto_fix(tmp_path, monkeypatch):
    _app, window = _create_window(tmp_path, monkeypatch)
    window.start_button.setEnabled(False)
    window.new_scan_button.setEnabled(False)
    window.stop_button.setEnabled(True)
    window.scan_finished({'error': 'Share unavailable'})
    assert window.start_button.isEnabled()
    assert window.new_scan_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.label.text() == 'Scan failed'
    assert window.scan_history.scans() == []
    window.close()


def test_close_waits_for_background_thread_without_blocking_ui(tmp_path, monkeypatch):
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QCloseEvent
    import threading
    _app, window = _create_window(tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    class WaitingWorker(QThread):
        def run(self):
            started.set()
            release.wait(5)

        def request_stop(self):
            release.set()

    worker = WaitingWorker()
    window._start_worker(worker)
    assert started.wait(2)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window._closing
    assert worker.wait(2000)
    final_event = QCloseEvent()
    window.closeEvent(final_event)
    assert final_event.isAccepted()
    window.close()


@pytest.mark.parametrize('message', [
    'Auto-fix finished.',
    'Auto-fix finished with 1 failure(s). See log.',
    'Auto-fix cancelled.',
])
def test_auto_fix_terminal_status_replaces_progress_on_repeated_runs(tmp_path, monkeypatch, message):
    _app, window = _create_window(tmp_path, monkeypatch)
    try:
        for terminal_message in [message, 'Auto-fix finished.']:
            window.auto_fix_progress.setVisible(True)
            window.auto_fix_stop_button.setVisible(True)
            window.auto_fix_stop_button.setEnabled(False)
            window.update_auto_fix_progress(1, 1)
            assert window.label.text() == 'Auto-fixing 1/1'

            window.auto_fix_finished(terminal_message)

            assert window.label.text() == terminal_message
            assert window.auto_fix_progress.isHidden()
            assert window.auto_fix_stop_button.isHidden()
            assert window.auto_fix_stop_button.isEnabled()
            assert window._active_auto_fix_keys == set()
    finally:
        window.close()


def _prepare_scan_controls(window, tmp_path, monkeypatch):
    window.scan_path_settings_path = str(tmp_path / 'scan_path_settings.json')
    monkeypatch.setattr(window, '_start_worker', lambda worker: None)
    monkeypatch.setattr(window, '_handle_auto_fix_after_scan', lambda: None)
    window.add_issue(str(tmp_path / 'movie.mkv'), 'No audio stream found')
    window.update_progress(9, 9, 94.3, 0, 7, 2)


@pytest.mark.parametrize('start_method', ['start_scan', 'start_fresh_scan'])
def test_new_scan_resets_previous_counters_even_if_it_fails(tmp_path, monkeypatch, start_method):
    _app, window = _create_window(tmp_path, monkeypatch)
    try:
        _prepare_scan_controls(window, tmp_path, monkeypatch)
        window.scan_finished({'bad_files': [], 'stats': {'scanned_files': 9}})
        saved_history = window.scan_history.scans()
        assert len(saved_history) == 1
        window.scan_media_folder_edit.setText(str(tmp_path / 'missing'))

        getattr(window, start_method)()

        expected = 'Files scanned: 0 | Issues: 0 | Speed: 0.0/s | ETA: -- | Cache: --'
        assert window.stats.text() == expected
        assert window.windowTitle() == 'NAS Media Validator — Issues: 0'
        assert window.progress.value() == 0
        assert window.progress.maximum() > 0  # Not an indeterminate busy bar.
        assert window.cache_hits == window.cache_misses == 0
        window.scan_finished({'error': 'Share unavailable'})
        assert window.label.text() == 'Scan failed'
        assert window.stats.text() == expected
        assert window.start_button.isEnabled()
        assert window.new_scan_button.isEnabled()
        assert not window.stop_button.isEnabled()
        assert window.scan_history.scans() == saved_history

        # A valid retry can still progress and finish normally.
        window.scan_media_folder_edit.setText(str(tmp_path))
        window.start_scan()
        window.update_progress(1, 1, 2, 0, 0, 1)
        window.scan_finished({'bad_files': [], 'stats': {'scanned_files': 1}})
        assert window.label.text() == 'Scan Complete'
        assert 'Files scanned: 1 | Issues: 0' in window.stats.text()
        assert len(window.scan_history.scans()) == 2
    finally:
        window.close()


def test_resuming_preserves_previous_results_and_active_scan_cannot_be_reset(tmp_path, monkeypatch):
    _app, window = _create_window(tmp_path, monkeypatch)
    try:
        _prepare_scan_controls(window, tmp_path, monkeypatch)
        window.scan_finished({'cancelled': True, 'resume_after': str(tmp_path / 'movie.mkv'),
                              'bad_files': [], 'stats': {'scanned_files': 9}})
        counters = window.stats.text()
        title = window.windowTitle()
        window.start_scan()
        assert window._current_scan_is_resume
        assert window.worker.resume_after == str(tmp_path / 'movie.mkv')
        assert window.table.rowCount() == 1
        assert window.stats.text() == counters
        assert window.windowTitle() == title
        assert window.library_stats_total['scanned_files'] == 9

        monkeypatch.setattr(window.worker, 'isRunning', lambda: True)
        window.start_fresh_scan()
        assert window.resume_after == str(tmp_path / 'movie.mkv')
        assert window.stats.text() == counters
        assert window.table.rowCount() == 1
    finally:
        window.close()
