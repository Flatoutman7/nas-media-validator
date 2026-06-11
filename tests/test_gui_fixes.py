import os

import pytest

from nas_checker.gui.fixes import (
    ACTION_FFMPEG,
    ACTION_MANUAL,
    ACTION_RADARR,
    ACTION_SONARR,
    classify_fix_action,
)
from nas_checker.scan.issues import (
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_HDR_DETECTED,
    ISSUE_NO_AUDIO,
    ISSUE_TENBIT_H264,
    make_issue,
)


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
    return app, window


def test_ffmpeg_fixable_issue_maps_to_ffmpeg_action():
    action = classify_fix_action(
        r"Z:\Movies\Example.mkv",
        [
            make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv"),
            make_issue(ISSUE_TENBIT_H264, "10bit H.264 (bad for Plex)"),
        ],
    )

    assert action.action_id == ACTION_FFMPEG
    assert action.fixable is True
    assert action.auto_fix_eligible is True
    assert action.label == "Auto-fix with ffmpeg"


def test_missing_audio_tv_episode_maps_to_sonarr_redownload():
    action = classify_fix_action(
        r"Z:\Shows\Example - S01E02.mkv",
        [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
    )

    assert action.action_id == ACTION_SONARR
    assert action.fixable is True
    assert action.auto_fix_eligible is False
    assert action.label == "Redownload via Sonarr"


def test_missing_audio_movie_maps_to_radarr_redownload():
    action = classify_fix_action(
        r"Z:\Movies\Example Movie (2024).mkv",
        [make_issue(ISSUE_NO_AUDIO, "No audio stream found")],
    )

    assert action.action_id == ACTION_RADARR
    assert action.fixable is True
    assert action.auto_fix_eligible is False
    assert action.label == "Redownload via Radarr"


def test_manual_review_issue_is_not_fixable():
    action = classify_fix_action(
        r"Z:\Movies\Example.mkv",
        [make_issue(ISSUE_HDR_DETECTED, "HDR detected")],
    )

    assert action.action_id == ACTION_MANUAL
    assert action.fixable is False
    assert action.auto_fix_eligible is False
    assert action.label == "No automatic fix / manual review"


def test_fixes_rows_are_selectable_and_click_toggle_checkboxes(tmp_path, monkeypatch):
    _app, window = _create_window(tmp_path, monkeypatch)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView

    window.add_issue(
        r"Z:\Movies\fixable.mkv",
        make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv"),
    )
    window.add_issue(
        r"Z:\Movies\manual.mkv",
        make_issue(ISSUE_HDR_DETECTED, "HDR detected"),
    )

    table = window.fixes_table
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection

    fixable_select_item = table.item(0, 0)
    assert fixable_select_item.flags() & Qt.ItemIsUserCheckable
    assert fixable_select_item.flags() & Qt.ItemIsEnabled
    assert fixable_select_item.checkState() == Qt.Unchecked

    window._on_fixes_cell_clicked(0, 1)

    assert fixable_select_item.checkState() == Qt.Checked
    assert table.selectionModel().isRowSelected(0, table.rootIndex())
    assert "Selected: 1" in window.fixes_status_label.text()

    manual_select_item = table.item(1, 0)
    assert manual_select_item.flags() & Qt.ItemIsUserCheckable
    assert not manual_select_item.flags() & Qt.ItemIsEnabled

    window._on_fixes_cell_clicked(1, 1)

    assert manual_select_item.checkState() == Qt.Unchecked
    assert table.selectionModel().isRowSelected(1, table.rootIndex())

    window.close()


def test_fixes_select_column_mouse_click_toggles_checkbox(tmp_path, monkeypatch):
    app, window = _create_window(tmp_path, monkeypatch)

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.add_issue(
        r"Z:\Movies\fixable.mkv",
        make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv"),
    )

    table = window.fixes_table
    select_item = table.item(0, 0)
    assert select_item.checkState() == Qt.Unchecked

    window.show()
    app.processEvents()

    select_rect = table.visualItemRect(select_item)
    assert select_rect.isValid()

    QTest.mouseClick(
        table.viewport(), Qt.LeftButton, Qt.NoModifier, select_rect.center()
    )
    app.processEvents()

    assert select_item.checkState() == Qt.Checked
    assert "Selected: 1" in window.fixes_status_label.text()

    QTest.mouseClick(
        table.viewport(), Qt.LeftButton, Qt.NoModifier, select_rect.center()
    )
    app.processEvents()

    assert select_item.checkState() == Qt.Unchecked
    assert "Selected: 0" in window.fixes_status_label.text()

    window.close()
