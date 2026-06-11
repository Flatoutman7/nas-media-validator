import json
import time

from health.scan_metadata_cache import ScanMetadataCache, canonicalize_path_key
from nas_checker.scan.issues import make_issue
from nas_checker.scan.issues import ISSUE_CONTAINER_NOT_ALLOWED


def test_canonicalize_path_key_windows_casing():
    assert canonicalize_path_key(r"Z:\Media\Show.mkv") == canonicalize_path_key(
        r"z:/media/show.mkv"
    )


def test_cache_hit_and_miss_on_mtime_change(tmp_path, monkeypatch):
    media = tmp_path / "file.mp4"
    media.write_bytes(b"x" * 2_000_000)
    db_path = str(tmp_path / "cache.db")

    calls = {"count": 0}

    def fake_analyze(file_path, rules_settings=None):
        calls["count"] += 1
        issues = [
            make_issue(ISSUE_CONTAINER_NOT_ALLOWED, "Container is not allowed: mkv")
        ]
        stats = {"container_is_allowed": False, "subtitle_tracks": 0}
        return issues, stats

    monkeypatch.setattr(
        "health.scan_metadata_cache.analyze_file_uncached", fake_analyze
    )

    cache = ScanMetadataCache(db_path=db_path, rules_settings={"containers": ["mp4"]})
    issues1, _stats1, from_cache1 = cache.analyze_file_cached(str(media))
    issues2, _stats2, from_cache2 = cache.analyze_file_cached(str(media))

    assert from_cache1 is False
    assert from_cache2 is True
    assert calls["count"] == 1
    assert issues1[0]["code"] == ISSUE_CONTAINER_NOT_ALLOWED

    time.sleep(0.01)
    media.write_bytes(b"x" * 2_000_001)
    issues3, _stats3, from_cache3 = cache.analyze_file_cached(str(media))
    assert from_cache3 is False
    assert calls["count"] == 2
    assert issues3[0]["code"] == ISSUE_CONTAINER_NOT_ALLOWED


def test_cache_invalidates_on_rules_hash_change(tmp_path, monkeypatch):
    media = tmp_path / "file.mp4"
    media.write_bytes(b"x" * 2_000_000)
    db_path = str(tmp_path / "cache.db")

    calls = {"count": 0}

    def fake_analyze(file_path, rules_settings=None):
        calls["count"] += 1
        return [], {"container_is_allowed": True, "subtitle_tracks": 0}

    monkeypatch.setattr(
        "health.scan_metadata_cache.analyze_file_uncached", fake_analyze
    )

    cache_a = ScanMetadataCache(
        db_path=db_path,
        rules_settings={"containers": ["mp4"], "video_codecs": ["hevc"]},
    )
    cache_a.analyze_file_cached(str(media))

    cache_b = ScanMetadataCache(
        db_path=db_path,
        rules_settings={"containers": ["mp4", "mkv"], "video_codecs": ["hevc"]},
    )
    _issues, _stats, from_cache = cache_b.analyze_file_cached(str(media))

    assert from_cache is False
    assert calls["count"] == 2
