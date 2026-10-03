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


def test_close_closes_connections_created_by_workers(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    import pytest
    cache = ScanMetadataCache(str(tmp_path / 'cache.db'))
    with ThreadPoolExecutor(max_workers=1) as pool:
        conn = pool.submit(cache._conn).result()
    cache.close()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute('SELECT 1')


def test_transient_probe_error_is_not_cached(tmp_path, monkeypatch):
    media = tmp_path / 'file.mp4'
    media.write_bytes(b'test')
    results = iter([([], {'media_info_error': True}), ([], {'audio_found': True})])
    monkeypatch.setattr('health.scan_metadata_cache.analyze_file_uncached',
                        lambda *a, **k: next(results))
    cache = ScanMetadataCache(str(tmp_path / 'cache.db'))
    try:
        assert cache.analyze_file_cached(str(media))[2] is False
        assert cache.analyze_file_cached(str(media))[2] is False
        assert cache.analyze_file_cached(str(media))[2] is True
    finally:
        cache.close()


def test_unavailable_cache_falls_back_to_analysis(tmp_path, monkeypatch):
    media = tmp_path / 'file.mp4'
    media.write_bytes(b'test')
    monkeypatch.setattr('health.scan_metadata_cache.analyze_file_uncached',
                        lambda *a, **k: ([], {'audio_found': True}))
    cache = ScanMetadataCache(str(tmp_path / 'missing' / 'cache.db'))
    try:
        assert cache.analyze_file_cached(str(media)) == ([], {'audio_found': True}, False)
    finally:
        cache.close()


def test_posix_cache_keys_preserve_case_and_spaces():
    import os
    if os.name != 'nt':
        assert canonicalize_path_key('/media/Movie.mp4') != canonicalize_path_key('/media/movie.mp4')
        assert canonicalize_path_key('/media/movie.mp4 ') != canonicalize_path_key('/media/movie.mp4')


def test_unc_cache_keys_normalize_case_and_separators():
    assert canonicalize_path_key(r'\\NAS\Media\Show.mkv') == canonicalize_path_key('//nas/media/show.mkv')


def test_legacy_cached_probe_errors_are_retried(tmp_path, monkeypatch):
    media = tmp_path / 'file.mp4'
    media.write_bytes(b'test')
    cache = ScanMetadataCache(str(tmp_path / 'cache.db'))
    try:
        cache._save_cached(str(media), cache._get_file_meta(str(media)), [],
                           {'media_info_error': True}, 'computed')
        monkeypatch.setattr('health.scan_metadata_cache.analyze_file_uncached',
                            lambda *a, **k: ([], {'audio_found': True}))
        assert cache.analyze_file_cached(str(media)) == ([], {'audio_found': True}, False)
    finally:
        cache.close()
