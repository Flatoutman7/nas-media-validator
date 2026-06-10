import os
import sys

import pytest

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from nas_checker.scan import rules
from nas_checker.scan.issues import (
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_HDR_DETECTED,
    ISSUE_TENBIT_H264,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    issue_code,
)


def _hevc_aac_streams():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24000/1001",
                "pix_fmt": "yuv420p10le",
                "color_transfer": "bt709",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }


def _mkv_h264_streams():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "bits_per_raw_sample": "10",
            },
            {"codec_type": "audio", "codec_name": "ac3"},
            {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle"},
        ]
    }


def _hdr_streams():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "color_transfer": "smpte2084",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }


@pytest.fixture
def media_file(tmp_path, monkeypatch):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(rules, "get_media_info", lambda _f: _hevc_aac_streams())
    return str(path)


def test_analyze_file_clean_mp4(media_file):
    issues, stats = rules.analyze_file(media_file)
    assert issues == []
    assert stats["video_found"] is True
    assert stats["audio_found"] is True


def test_analyze_file_mkv_container_flags_issue(tmp_path, monkeypatch):
    path = tmp_path / "sample.mkv"
    path.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(rules, "get_media_info", lambda _f: _hevc_aac_streams())

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert ISSUE_CONTAINER_NOT_ALLOWED in codes
    assert stats["container_is_allowed"] is False


def test_analyze_file_tenbit_h264(tmp_path, monkeypatch):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(rules, "get_media_info", lambda _f: _mkv_h264_streams())

    issues, _stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert ISSUE_VIDEO_CODEC_NOT_ALLOWED in codes
    assert ISSUE_TENBIT_H264 in codes


def test_analyze_file_hdr_detected(tmp_path, monkeypatch):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(rules, "get_media_info", lambda _f: _hdr_streams())

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert ISSUE_HDR_DETECTED in codes
    assert stats["hdr_detected"] is True


def test_analyze_file_wrong_resolution(tmp_path, monkeypatch):
    path = tmp_path / "Show - 1080p.mp4"
    path.write_bytes(b"x" * 2_000_000)

    streams = _hevc_aac_streams()
    streams["streams"][0]["height"] = 720
    monkeypatch.setattr(rules, "get_media_info", lambda _f: streams)

    issues, stats = rules.analyze_file(path)
    assert stats["wrong_resolution_issue"] is True
    assert any("Wrong resolution" in i["message"] for i in issues)


def test_analyze_file_respects_rule_toggles(tmp_path, monkeypatch):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(rules, "get_media_info", lambda _f: _hdr_streams())

    settings = {
        "containers": ["mp4"],
        "video_codecs": ["hevc"],
        "audio_codecs": ["aac"],
        "check_hdr": False,
        "check_subtitles": False,
    }
    issues, _stats = rules.analyze_file(path, rules_settings=settings)
    codes = {issue_code(i) for i in issues}
    assert ISSUE_HDR_DETECTED not in codes


def test_get_media_info_checks_returncode(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "invalid data"

    monkeypatch.setattr(rules.subprocess, "run", lambda *a, **k: Result())

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        rules.get_media_info("file.mp4")
