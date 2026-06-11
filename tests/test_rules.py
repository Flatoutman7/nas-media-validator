import pytest

from nas_checker.scan import rules
from nas_checker.scan.issues import (
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_HDR_DETECTED,
    ISSUE_TENBIT_H264,
    ISSUE_WRONG_RESOLUTION,
    issue_code,
)
from nas_checker.scan.scan_rules_settings import DEFAULT_SCAN_RULES_SETTINGS


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


def test_default_scan_rules_match_optimized_profile():
    assert DEFAULT_SCAN_RULES_SETTINGS == {
        "containers": ["mp4", "mkv"],
        "video_codecs": ["hevc", "h264"],
        "audio_codecs": ["aac", "ac3", "eac3"],
        "min_file_size_bytes": 1_000_000,
        "check_subtitles": False,
        "check_hdr": False,
        "check_tenbit_h264": True,
        "check_multiple_audio": False,
        "check_multiple_subtitle": False,
        "check_multiple_commentary": True,
        "check_wrong_resolution": True,
    }


def test_analyze_file_disallowed_container_flags_issue(tmp_path, monkeypatch):
    path = tmp_path / "sample.avi"
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
    assert ISSUE_TENBIT_H264 in codes


def test_analyze_file_hdr_default_is_not_noisy(tmp_path, monkeypatch):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(rules, "get_media_info", lambda _f: _hdr_streams())

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert ISSUE_HDR_DETECTED not in codes
    assert stats["hdr_detected"] is True


def test_analyze_file_wrong_resolution(tmp_path, monkeypatch):
    path = tmp_path / "Show - 1080p.mp4"
    path.write_bytes(b"x" * 2_000_000)

    streams = _hevc_aac_streams()
    streams["streams"][0]["height"] = 720
    monkeypatch.setattr(rules, "get_media_info", lambda _f: streams)

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert stats["wrong_resolution_issue"] is True
    assert ISSUE_WRONG_RESOLUTION in codes
    assert any("expected 1080p, found 720p" in i["message"] for i in issues)


def test_analyze_file_ignores_unknown_resolution_token(tmp_path, monkeypatch):
    path = tmp_path / "Show - 80p.mp4"
    path.write_bytes(b"x" * 2_000_000)

    streams = _hevc_aac_streams()
    streams["streams"][0]["height"] = 1080
    monkeypatch.setattr(rules, "get_media_info", lambda _f: streams)

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert stats["expected_resolution_height"] is None
    assert stats["wrong_resolution_issue"] is False
    assert ISSUE_WRONG_RESOLUTION not in codes


def test_analyze_file_ignores_resolution_substrings(tmp_path, monkeypatch):
    path = tmp_path / "Show source1080pnotes.mp4"
    path.write_bytes(b"x" * 2_000_000)

    streams = _hevc_aac_streams()
    streams["streams"][0]["height"] = 720
    monkeypatch.setattr(rules, "get_media_info", lambda _f: streams)

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert stats["expected_resolution_height"] is None
    assert stats["wrong_resolution_issue"] is False
    assert ISSUE_WRONG_RESOLUTION not in codes


@pytest.mark.parametrize("height", [360, 480, 576, 720, 1080, 1440, 2160, 4320])
def test_analyze_file_detects_common_resolution_tokens(tmp_path, monkeypatch, height):
    path = tmp_path / f"Show - {height}p.mkv"
    path.write_bytes(b"x" * 2_000_000)

    streams = _hevc_aac_streams()
    streams["streams"][0]["height"] = height
    monkeypatch.setattr(rules, "get_media_info", lambda _f: streams)

    issues, stats = rules.analyze_file(path)
    codes = {issue_code(i) for i in issues}
    assert stats["expected_resolution_height"] == height
    assert stats["wrong_resolution_issue"] is False
    assert ISSUE_WRONG_RESOLUTION not in codes


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
