import threading

from nas_checker.scan.main import run_scan


class FakeScanMetadataCache:
    instances = []

    def __init__(self, db_path, rules_settings):
        self.db_path = db_path
        self.rules_settings = rules_settings
        self.closed = False
        FakeScanMetadataCache.instances.append(self)

    def analyze_file_cached(self, file_path):
        return [], {}, False

    def close(self):
        self.closed = True


def _patch_run_scan_dependencies(monkeypatch, files):
    FakeScanMetadataCache.instances = []
    monkeypatch.setattr(
        "nas_checker.scan.main.ScanMetadataCache", FakeScanMetadataCache
    )
    monkeypatch.setattr("nas_checker.scan.main.run_preflight_checks", lambda **_: [])
    monkeypatch.setattr("nas_checker.scan.main.load_scan_rules_settings", lambda: {})
    monkeypatch.setattr(
        "nas_checker.scan.main.scan_folder", lambda *_args, **_kwargs: files
    )
    monkeypatch.setattr(
        "nas_checker.scan.main.save_report", lambda *_args, **_kwargs: None
    )


def test_run_scan_closes_cache_on_normal_completion(monkeypatch):
    _patch_run_scan_dependencies(monkeypatch, ["movie.mp4"])

    result = run_scan(path="Z:/Media", max_workers=1, use_cache=True)

    assert result["cancelled"] is False
    assert len(FakeScanMetadataCache.instances) == 1
    assert FakeScanMetadataCache.instances[0].closed is True


def test_run_scan_closes_cache_on_cancellation(monkeypatch):
    stop_event = threading.Event()
    stop_event.set()
    _patch_run_scan_dependencies(monkeypatch, ["movie.mp4"])

    result = run_scan(
        path="Z:/Media",
        stop_event=stop_event,
        max_workers=1,
        use_cache=True,
    )

    assert result["cancelled"] is True
    assert len(FakeScanMetadataCache.instances) == 1
    assert FakeScanMetadataCache.instances[0].closed is True
