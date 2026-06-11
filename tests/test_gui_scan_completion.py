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
