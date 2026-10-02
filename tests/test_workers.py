import sys

import pytest

pytest.importorskip('PySide6')
workers = pytest.importorskip("nas_checker.workers.worker")


def test_scan_worker_emits_error_payload(monkeypatch):
    def fail(*a, **k):
        raise OSError('share unavailable')
    monkeypatch.setattr(workers.scan_main, 'run_scan', fail)
    worker = workers.ScanWorker('Z:/Media')
    payloads = []
    worker.finished.connect(payloads.append)
    worker.run()
    assert payloads == [{'error': 'share unavailable', 'cancelled': False}]


@pytest.mark.parametrize('failure', ['backup', 'no_video', 'probe', 'ffmpeg', 'launch', 'replace'])
def test_autofix_preserves_original_on_failure(tmp_path, monkeypatch, failure):
    source = tmp_path / 'movie.mp4'
    source.write_bytes(b'original')
    output = tmp_path / 'movie_auto_fix_tmp.mp4'
    monkeypatch.setattr(workers, 'load_scan_rules_settings', lambda: {})
    monkeypatch.setattr(workers, 'build_ffmpeg_command', lambda *a: (['fake'], str(output)))
    monkeypatch.setattr(workers, 'analyze_file', lambda *a, **k: ([], {
        'audio_found': True, 'video_found': failure != 'no_video',
        'media_info_error': failure == 'probe'}))
    if failure == 'backup':
        monkeypatch.setattr(workers, 'backup_original_file', lambda _: None)
    if failure == 'replace':
        def replace(*a):
            raise PermissionError('locked')
        monkeypatch.setattr(workers.os, 'replace', replace)

    def run(cmd):
        if failure == 'launch':
            raise FileNotFoundError('ffmpeg missing')
        output.write_bytes(b'converted')
        return 1 if failure == 'ffmpeg' else 0

    worker = workers.AutoFixWorker([str(source)], {str(source): []})
    monkeypatch.setattr(worker, '_run_ffmpeg', run)
    messages = []
    worker.finished.connect(messages.append)
    worker.run()
    assert source.read_bytes() == b'original'
    assert not output.exists()
    assert len(messages) == 1 and 'failure' in messages[0]


@pytest.mark.parametrize('existing_destination', [False, True])
def test_container_conversion_uses_correct_extension(tmp_path, monkeypatch, existing_destination):
    source = tmp_path / 'movie.avi'
    source.write_bytes(b'original')
    destination = tmp_path / 'movie.mp4'
    output = tmp_path / 'movie_auto_fix_tmp.mp4'
    if existing_destination:
        destination.write_bytes(b'other movie')
    monkeypatch.setattr(workers, 'load_scan_rules_settings', lambda: {})
    monkeypatch.setattr(workers, 'build_ffmpeg_command', lambda *a: (['fake'], str(output)))
    monkeypatch.setattr(workers, 'analyze_file', lambda *a, **k: ([], {
        'audio_found': True, 'video_found': True}))
    worker = workers.AutoFixWorker([str(source)], {str(source): []})

    def run(cmd):
        output.write_bytes(b'converted')
        return 0

    monkeypatch.setattr(worker, '_run_ffmpeg', run)
    worker.run()
    assert not output.exists()
    if existing_destination:
        assert source.read_bytes() == b'original'
        assert destination.read_bytes() == b'other movie'
    else:
        assert not source.exists()
        assert destination.read_bytes() == b'converted'
        assert (tmp_path / 'movie.avi.bak').read_bytes() == b'original'


def test_silent_process_can_be_cancelled():
    import threading
    import time
    worker = workers.AutoFixWorker([])
    timer = threading.Timer(0.2, worker.request_stop)
    timer.start()
    started = time.monotonic()
    try:
        worker._run_ffmpeg([sys.executable, '-c', 'import time; time.sleep(30)'])
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5


@pytest.mark.parametrize('service,worker_type,client_type,method', [
    ('sonarr', workers.SonarrRedownloadWorker, workers.SonarrClient, 'find_series_id'),
    ('radarr', workers.RadarrRedownloadWorker, workers.RadarrClient, 'find_movie_id')])
def test_redownload_network_error_reports_completion(monkeypatch, service, worker_type, client_type, method):
    monkeypatch.setattr(workers, 'load_arr_config', lambda: {service: {
        'enabled': True, 'base_url': 'http://example.invalid', 'api_key': 'test'}})

    def fail(*args):
        raise OSError('offline')

    monkeypatch.setattr(client_type, method, fail)
    worker = worker_type('Test')
    messages = []
    worker.finished.connect(messages.append)
    worker.run()
    assert len(messages) == 1
    assert 'failed' in messages[0]


def test_radarr_rejected_command_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(workers, 'load_arr_config', lambda: {'radarr': {
        'enabled': True, 'base_url': 'http://example.invalid', 'api_key': 'test'}})
    monkeypatch.setattr(workers.RadarrClient, 'find_movie_id', lambda *a: 42)
    monkeypatch.setattr(workers.RadarrClient, 'missing_movie_search',
                        lambda *a: {'error': 'rejected', 'status': 400})
    worker = workers.RadarrRedownloadWorker('Test')
    messages = []
    worker.finished.connect(messages.append)
    worker.run()
    assert len(messages) == 1
    assert 'failed' in messages[0]
