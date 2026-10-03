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


def test_stop_during_final_drain_does_not_export(monkeypatch):
    _patch_run_scan_dependencies(monkeypatch, ['a.mp4', 'b.mp4'])
    stop = threading.Event()
    reports = []
    monkeypatch.setattr('nas_checker.scan.main.save_report', lambda *a, **k: reports.append(a))

    def progress(*_args):
        stop.set()

    result = run_scan(path='Z:/Media', max_workers=1, stop_event=stop,
                      progress_callback=progress)
    assert result['cancelled'] is True
    assert reports == []


def test_cancellation_waits_for_active_cache_users(monkeypatch):
    _patch_run_scan_dependencies(monkeypatch, ['a.mp4'])
    stop = threading.Event()
    active_finished = threading.Event()

    def analyze(self, path):
        stop.set()
        assert not self.closed
        active_finished.set()
        return [], {}, False

    def close(self):
        assert active_finished.is_set()
        self.closed = True

    monkeypatch.setattr(FakeScanMetadataCache, 'analyze_file_cached', analyze)
    monkeypatch.setattr(FakeScanMetadataCache, 'close', close)
    result = run_scan(path='Z:/Media', max_workers=1, stop_event=stop)
    assert result['cancelled'] is True


def test_cancelled_out_of_order_results_are_not_counted_twice(monkeypatch):
    _patch_run_scan_dependencies(monkeypatch, ['a.mp4', 'b.mp4'])
    stop = threading.Event()
    second_finished = threading.Event()

    def analyze(self, path):
        if path == 'a.mp4':
            assert second_finished.wait(2)
        else:
            stop.set()
            second_finished.set()
        return [], {}, False

    monkeypatch.setattr(FakeScanMetadataCache, 'analyze_file_cached', analyze)
    result = run_scan(path='Z:/Media', max_workers=2, stop_event=stop)
    expected = {None: 0, 'a.mp4': 1, 'b.mp4': 2}
    assert result['stats']['scanned_files'] == expected[result['resume_after']]
