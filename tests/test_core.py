import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from health.hardware import recommend_scan_workers
from health.scan_metadata_cache import ScanMetadataCache, canonicalize_path_key
from nas_checker.media.autofix import build_ffmpeg_command
from nas_checker.scan.issues import (
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_NO_AUDIO,
    ISSUE_TENBIT_H264,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    make_issue,
    normalize_issues,
)
from nas_checker.scan.rules import analyze_file
from nas_checker.scan.scan_rules_settings import DEFAULT_SCAN_RULES_SETTINGS

HEVC_AAC_MP4_STREAMS = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "24000/1001",
            "color_transfer": "bt709",
        },
        {"codec_type": "audio", "codec_name": "aac", "disposition": {}, "tags": {}},
    ]
}

H264_AAC_AVI_STREAMS = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "24/1",
        },
        {"codec_type": "audio", "codec_name": "aac", "disposition": {}, "tags": {}},
    ]
}

TENBIT_H264_STREAMS = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p10le",
            "bits_per_raw_sample": 10,
            "avg_frame_rate": "24/1",
        },
        {"codec_type": "audio", "codec_name": "aac", "disposition": {}, "tags": {}},
    ]
}


class AnalyzeFileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_path = os.path.join(self.temp_dir.name, "sample.mp4")
        with open(self.media_path, "wb") as handle:
            handle.write(b"\x00" * 2_000_000)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("nas_checker.scan.rules.get_media_info")
    def test_analyze_file_passes_hevc_aac(self, mock_get_media_info):
        mock_get_media_info.return_value = HEVC_AAC_MP4_STREAMS
        issues, stats = analyze_file(self.media_path)
        self.assertEqual(issues, [])
        self.assertTrue(stats["video_found"])
        self.assertTrue(stats["audio_found"])

    @patch("nas_checker.scan.rules.get_media_info")
    def test_analyze_file_flags_disallowed_container(self, mock_get_media_info):
        avi_path = os.path.join(self.temp_dir.name, "sample.avi")
        with open(avi_path, "wb") as handle:
            handle.write(b"\x00" * 2_000_000)
        mock_get_media_info.return_value = H264_AAC_AVI_STREAMS
        issues, stats = analyze_file(avi_path)
        codes = {i["code"] for i in issues}
        self.assertIn(ISSUE_CONTAINER_NOT_ALLOWED, codes)
        self.assertFalse(stats["container_is_allowed"])

    @patch("nas_checker.scan.rules.get_media_info")
    def test_analyze_file_flags_tenbit_h264(self, mock_get_media_info):
        mock_get_media_info.return_value = TENBIT_H264_STREAMS
        issues, _stats = analyze_file(self.media_path)
        codes = {i["code"] for i in issues}
        self.assertIn(ISSUE_TENBIT_H264, codes)

    @patch("nas_checker.scan.rules.get_media_info")
    def test_analyze_file_respects_disabled_subtitle_check(self, mock_get_media_info):
        streams = json.loads(json.dumps(HEVC_AAC_MP4_STREAMS))
        streams["streams"].append({"codec_type": "subtitle", "codec_name": "subrip"})
        mock_get_media_info.return_value = streams
        settings = dict(DEFAULT_SCAN_RULES_SETTINGS)
        settings["check_subtitles"] = False
        issues, _stats = analyze_file(self.media_path, rules_settings=settings)
        codes = {i["code"] for i in issues}
        self.assertNotIn("subtitle_track", codes)

    @patch("nas_checker.scan.rules.get_media_info")
    def test_analyze_file_small_file_threshold(self, mock_get_media_info):
        small_path = os.path.join(self.temp_dir.name, "tiny.mp4")
        with open(small_path, "wb") as handle:
            handle.write(b"\x00" * 100)
        mock_get_media_info.return_value = HEVC_AAC_MP4_STREAMS
        issues, stats = analyze_file(small_path)
        self.assertTrue(stats["min_file_size_issue"])
        self.assertEqual(issues[0]["code"], "file_small")


class BuildFfmpegCommandTests(unittest.TestCase):
    def test_container_fix_triggers_mp4_output(self):
        issues = [
            make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv")
        ]
        cmd, output_path = build_ffmpeg_command("Z:/Movies/sample.mkv", issues)
        self.assertIsNotNone(cmd)
        self.assertTrue(output_path.endswith(".mp4"))
        self.assertIn("-f", cmd)
        self.assertIn("mp4", cmd)

    def test_no_audio_skips_fix(self):
        issues = [make_issue(ISSUE_NO_AUDIO, "No audio stream found")]
        cmd, output_path = build_ffmpeg_command("Z:/Movies/sample.mkv", issues)
        self.assertIsNone(cmd)
        self.assertIsNone(output_path)

    @patch("nas_checker.media.autofix.detect_nvidia_gpu", return_value=False)
    def test_cpu_fallback_for_hevc_transcode(self, _mock_gpu):
        issues = [
            make_issue(
                ISSUE_VIDEO_CODEC_NOT_ALLOWED, "Video codec is h264, not allowed"
            )
        ]
        cmd, _output = build_ffmpeg_command("Z:/Movies/sample.mp4", issues)
        self.assertIsNotNone(cmd)
        self.assertIn("libx265", cmd)

    @patch("nas_checker.media.autofix.detect_nvidia_gpu", return_value=True)
    def test_nvenc_used_when_gpu_available(self, _mock_gpu):
        issues = [make_issue(ISSUE_TENBIT_H264, "10bit H.264 (bad for Plex)")]
        cmd, _output = build_ffmpeg_command("Z:/Movies/sample.mp4", issues)
        self.assertIsNotNone(cmd)
        self.assertIn("hevc_nvenc", cmd)


class ScanMetadataCacheTests(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, "cache"):
            self.cache.close()

    @patch("nas_checker.scan.rules.get_media_info")
    def test_cache_hit_and_miss(self, mock_get_media_info):
        mock_get_media_info.return_value = HEVC_AAC_MP4_STREAMS
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "cache.db")
            media_path = os.path.join(tmp, "movie.mp4")
            with open(media_path, "wb") as handle:
                handle.write(b"\x00" * 2_000_000)

            self.cache = ScanMetadataCache(db_path=db_path)
            issues1, _stats1, from_cache1 = self.cache.analyze_file_cached(media_path)
            issues2, _stats2, from_cache2 = self.cache.analyze_file_cached(media_path)
            self.cache.close()

            self.assertFalse(from_cache1)
            self.assertTrue(from_cache2)
            self.assertEqual(issues1, issues2)

            self.cache = ScanMetadataCache(db_path=db_path)
            with open(media_path, "ab") as handle:
                handle.write(b"x")
            issues3, _stats3, from_cache3 = self.cache.analyze_file_cached(media_path)
            self.cache.close()

            self.assertFalse(from_cache3)

    @patch("nas_checker.scan.rules.get_media_info")
    def test_rules_hash_change_invalidates_cache(self, mock_get_media_info):
        mock_get_media_info.return_value = HEVC_AAC_MP4_STREAMS
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "cache.db")
            media_path = os.path.join(tmp, "movie.mp4")
            with open(media_path, "wb") as handle:
                handle.write(b"\x00" * 2_000_000)

            settings_a = dict(DEFAULT_SCAN_RULES_SETTINGS)
            settings_b = dict(DEFAULT_SCAN_RULES_SETTINGS)
            settings_b["check_tenbit_h264"] = False

            self.cache = ScanMetadataCache(db_path=db_path, rules_settings=settings_a)
            _issues1, _stats1, from_cache1 = self.cache.analyze_file_cached(media_path)
            self.cache.close()
            self.assertFalse(from_cache1)

            self.cache = ScanMetadataCache(db_path=db_path, rules_settings=settings_b)
            _issues2, _stats2, from_cache2 = self.cache.analyze_file_cached(media_path)
            self.cache.close()
            self.assertFalse(from_cache2)


class CanonicalizePathKeyTests(unittest.TestCase):
    def test_windows_case_insensitive(self):
        self.assertEqual(
            canonicalize_path_key(r"Z:\TV\Show\Episode.mp4"),
            canonicalize_path_key(r"z:/tv/show/episode.mp4"),
        )

    def test_empty_path(self):
        self.assertEqual(canonicalize_path_key(""), "")


class RecommendScanWorkersTests(unittest.TestCase):
    @patch("health.hardware.get_storage_profile")
    @patch("health.hardware.detect_nvidia_gpu", return_value=False)
    @patch("health.hardware.os.cpu_count", return_value=8)
    def test_network_worker_recommendation_is_conservative(
        self, _cpu, _gpu, mock_profile
    ):
        mock_profile.return_value = {
            "storage_class": "network",
            "estimated_read_mb_s": 60,
        }
        workers = recommend_scan_workers("Z:/")
        self.assertEqual(workers, 4)

    @patch("health.hardware.get_storage_profile")
    @patch("health.hardware.detect_nvidia_gpu", return_value=True)
    @patch("health.hardware.os.cpu_count", return_value=16)
    def test_nvme_worker_recommendation_scales_with_cpu(self, _cpu, _gpu, mock_profile):
        mock_profile.return_value = {
            "storage_class": "nvme",
            "estimated_read_mb_s": 1200,
        }
        workers = recommend_scan_workers("Z:/")
        self.assertEqual(workers, 24)


class IssueCompatibilityTests(unittest.TestCase):
    def test_normalize_legacy_string_issue(self):
        issues = normalize_issues(["Container is not allowed: mkv"])
        self.assertEqual(issues[0]["code"], ISSUE_CONTAINER_NOT_ALLOWED)


def test_smoke_imports():
    from nas_checker.scan.main import run_scan  # noqa: F401
    from health.scan_history import ScanHistory  # noqa: F401

    assert callable(run_scan)
    assert ScanHistory is not None
