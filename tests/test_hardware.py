from health.hardware import (
    evaluate_read_benchmark_result,
    get_scan_worker_recommendation,
    measure_read_throughput,
    recommend_scan_workers,
)
from nas_checker.scan.scan_path_settings import (
    EFFECTIVE_READ_MB_S_KEY,
    MEASURED_READ_CONFIDENCE_KEY,
    MEASURED_READ_MB_S_KEY,
    RAW_MEASURED_READ_MB_S_KEY,
    load_scan_path_settings,
    save_scan_path_settings,
)


def test_recommend_scan_workers_bounds(monkeypatch):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: True)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {"storage_class": "nvme", "estimated_read_mb_s": 1200},
    )

    workers = recommend_scan_workers("Z:/")
    assert workers == 24


def test_recommend_scan_workers_network_is_conservative(monkeypatch):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {"storage_class": "network", "estimated_read_mb_s": 60},
    )

    workers = recommend_scan_workers("Z:/")
    assert workers == 8


def test_recommend_scan_workers_hdd_caps_lower(monkeypatch):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {"storage_class": "hdd", "estimated_read_mb_s": 120},
    )

    assert recommend_scan_workers("D:/") == 6


def test_scan_worker_recommendation_details(monkeypatch):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 8)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: True)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {
            "drive_type": "fixed",
            "storage_class": "sata_ssd",
            "estimated_read_mb_s": 550,
        },
    )

    details = get_scan_worker_recommendation("C:/Media")

    assert details["workers"] == 8
    assert details["cpu_count"] == 8
    assert details["storage_class"] == "sata_ssd"
    assert details["drive_type"] == "fixed"
    assert details["estimated_read_mb_s"] == 550
    assert details["has_nvidia"] is True
    assert "SATA SSD" in details["reason"]


def test_measured_read_speed_tunes_network_workers(monkeypatch):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {
            "drive_type": "remote",
            "storage_class": "network",
            "estimated_read_mb_s": 60,
        },
    )

    details = get_scan_worker_recommendation("Z:/", measured_read_mb_s=180)

    assert details["workers"] == 12
    assert details["measured_read_mb_s"] == 180
    assert details["effective_measured_read_mb_s"] == 180
    assert details["raw_measured_read_mb_s"] == 180
    assert details["read_speed_source"] == "argument"
    assert "effective read speed" in details["reason"]


def test_implausible_network_read_speed_is_low_confidence(monkeypatch):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {
            "drive_type": "remote",
            "storage_class": "network",
            "estimated_read_mb_s": 60,
        },
    )

    details = get_scan_worker_recommendation("Z:/", measured_read_mb_s=4129)

    assert details["workers"] == 8
    assert details["measured_read_mb_s"] == 500.0
    assert details["effective_measured_read_mb_s"] == 500.0
    assert details["raw_measured_read_mb_s"] == 4129
    assert details["read_speed_confidence"] == "low"
    assert "cached/low-confidence result ignored" in details["reason"]
    assert "4129" not in details["reason"]


def test_first_plausible_read_benchmark_result_is_saved(monkeypatch, tmp_path):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {
            "drive_type": "remote",
            "storage_class": "network",
            "estimated_read_mb_s": 60,
        },
    )
    settings_path = tmp_path / "scan_path_settings.json"

    evaluation = evaluate_read_benchmark_result("Z:/Media", 180.0, None, "normal")
    save_scan_path_settings(
        {
            "media_folder": "Z:/Media",
            MEASURED_READ_MB_S_KEY: evaluation["effective_mb_s"],
            EFFECTIVE_READ_MB_S_KEY: evaluation["effective_mb_s"],
            RAW_MEASURED_READ_MB_S_KEY: evaluation["raw_mb_s"],
            MEASURED_READ_CONFIDENCE_KEY: evaluation["confidence"],
        },
        str(settings_path),
    )
    loaded = load_scan_path_settings(str(settings_path))

    assert evaluation["ignored"] is False
    assert loaded[MEASURED_READ_MB_S_KEY] == 180.0
    assert loaded[EFFECTIVE_READ_MB_S_KEY] == 180.0
    assert loaded[RAW_MEASURED_READ_MB_S_KEY] == 180.0
    assert loaded[MEASURED_READ_CONFIDENCE_KEY] == "normal"


def test_second_implausible_read_benchmark_keeps_previous_effective(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("health.hardware.os.cpu_count", lambda: 16)
    monkeypatch.setattr("health.hardware.detect_nvidia_gpu", lambda: False)
    monkeypatch.setattr(
        "health.hardware.get_storage_profile",
        lambda _path: {
            "drive_type": "remote",
            "storage_class": "network",
            "estimated_read_mb_s": 60,
        },
    )
    settings_path = tmp_path / "scan_path_settings.json"
    save_scan_path_settings(
        {
            "media_folder": "Z:/Media",
            MEASURED_READ_MB_S_KEY: 180.0,
            EFFECTIVE_READ_MB_S_KEY: 180.0,
            RAW_MEASURED_READ_MB_S_KEY: 180.0,
            MEASURED_READ_CONFIDENCE_KEY: "normal",
        },
        str(settings_path),
    )
    previous = load_scan_path_settings(str(settings_path))[EFFECTIVE_READ_MB_S_KEY]

    evaluation = evaluate_read_benchmark_result("Z:/Media", 4129.0, previous, "normal")
    save_scan_path_settings(
        {
            "media_folder": "Z:/Media",
            MEASURED_READ_MB_S_KEY: evaluation["effective_mb_s"],
            EFFECTIVE_READ_MB_S_KEY: evaluation["effective_mb_s"],
            RAW_MEASURED_READ_MB_S_KEY: evaluation["raw_mb_s"],
            MEASURED_READ_CONFIDENCE_KEY: evaluation["confidence"],
        },
        str(settings_path),
    )
    loaded = load_scan_path_settings(str(settings_path))

    assert evaluation["ignored"] is True
    assert "cached/implausible result ignored" in evaluation["ignore_reason"]
    assert loaded[MEASURED_READ_MB_S_KEY] == 180.0
    assert loaded[EFFECTIVE_READ_MB_S_KEY] == 180.0
    assert loaded[RAW_MEASURED_READ_MB_S_KEY] == 4129.0
    assert loaded[MEASURED_READ_CONFIDENCE_KEY] == "low"


def test_measure_read_throughput_reads_existing_media_files(tmp_path):
    media_file = tmp_path / "movie.mkv"
    media_file.write_bytes(b"a" * (2 * 1024 * 1024))
    ignored_file = tmp_path / "notes.txt"
    ignored_file.write_text("not media", encoding="utf-8")

    result = measure_read_throughput(
        str(tmp_path), max_bytes=1024 * 1024, sample_count=1
    )

    assert result["error"] is None
    assert result["bytes_read"] == 1024 * 1024
    assert result["files_sampled"] == 1
    assert result["mb_s"] > 0


def test_measure_read_throughput_reports_small_sample(tmp_path):
    first = tmp_path / "movie-a.mkv"
    second = tmp_path / "movie-b.mp4"
    first.write_bytes(b"a" * (1024 * 1024))
    second.write_bytes(b"b" * (1024 * 1024))

    result = measure_read_throughput(
        str(tmp_path), max_bytes=256 * 1024 * 1024, sample_count=2
    )

    assert result["error"] is None
    assert result["bytes_read"] == 2 * 1024 * 1024
    assert result["files_sampled"] == 2
    assert result["target_bytes"] == 256 * 1024 * 1024
    assert result["sample_too_small"] is True
    assert result["confidence"] == "low"
    assert "Sample is below" in result["message"]


def test_measure_read_throughput_handles_no_media_files(tmp_path):
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")

    result = measure_read_throughput(str(tmp_path), max_bytes=1024, sample_count=1)

    assert result["error"] == "no_media_files"
    assert result["bytes_read"] == 0
    assert result["files_sampled"] == 0
