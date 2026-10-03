import errno
import os

import pytest

from nas_checker.scan.main import run_scan
from nas_checker.scan.scanner import scan_folder


def test_missing_folder_fails_instead_of_returning_empty_results(tmp_path):
    missing = tmp_path / "disconnected-share"
    with pytest.raises(FileNotFoundError, match="disconnected-share"):
        list(scan_folder(str(missing)))


def test_failed_scan_preserves_previous_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("nas_checker.scan.main.run_preflight_checks", lambda **_: [])
    report = tmp_path / "bad_media_report.csv"
    report.write_text("previous results", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing"):
        run_scan(str(tmp_path / "missing"), max_workers=1, use_cache=False)
    assert report.read_text(encoding="utf-8") == "previous results"


def test_file_cannot_be_used_as_scan_folder(tmp_path):
    media_file = tmp_path / "movie.mp4"
    media_file.touch()
    with pytest.raises(NotADirectoryError):
        list(scan_folder(str(media_file)))


def test_empty_folder_is_accessible(tmp_path):
    assert list(scan_folder(str(tmp_path))) == []


def test_discovers_supported_media_in_nested_folders(tmp_path):
    nested = tmp_path / "Series with spaces"
    nested.mkdir()
    files = [tmp_path / "film.MP4", nested / "episode.mkv", nested / "clip.mov"]
    for media_file in files:
        media_file.touch()
    (nested / "notes.txt").touch()
    assert set(scan_folder(str(tmp_path))) == {str(path) for path in files}


def test_unreadable_subfolder_is_not_silently_skipped(tmp_path, monkeypatch):
    blocked = tmp_path / "unreadable"
    blocked.mkdir()
    original_scandir = os.scandir

    def scandir(path):
        if os.fspath(path) == str(blocked):
            raise PermissionError(errno.EACCES, "Access denied", str(blocked))
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    with pytest.raises(OSError, match="unreadable"):
        list(scan_folder(str(tmp_path)))
