import ctypes
import json
import os
import random
import subprocess
import time
from typing import Any

try:
    from nas_checker.scan.scanner import MEDIA_EXTENSIONS as SCANNER_MEDIA_EXTENSIONS
except Exception:
    SCANNER_MEDIA_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".m4v")

READ_BENCHMARK_EXTENSIONS = tuple(
    sorted({str(ext).lower() for ext in SCANNER_MEDIA_EXTENSIONS})
)
DEFAULT_READ_BENCHMARK_BYTES = 512 * 1024 * 1024
DEFAULT_READ_BENCHMARK_SAMPLE_COUNT = 10
MIN_CONFIDENT_READ_BENCHMARK_BYTES = 64 * 1024 * 1024
READ_BENCHMARK_CHUNK_BYTES = 4 * 1024 * 1024
NETWORK_IMPLAUSIBLE_READ_MB_S = 1250.0
NETWORK_CONSERVATIVE_READ_MB_S = 500.0
READ_BENCHMARK_PREVIOUS_MULTIPLIER_LIMIT = 2.0


def detect_nvidia_gpu() -> bool:
    """
    Best-effort NVIDIA GPU detection.

    Uses `nvidia-smi -L` when available. If it fails for any reason, returns False.
    """
    try:
        proc = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=2,
            check=False,
        )
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except Exception:
        return False


def _get_windows_drive_type(root_path: str) -> str:
    """
    Return a human-readable drive type for the given path's root drive.

    Uses WinAPI `GetDriveTypeW`.
    """
    drive = None
    if len(root_path) >= 2 and root_path[1] == ":":
        drive = root_path[:2]
    if not drive:
        # UNC paths, mounted paths, etc.
        return "remote"

    drive_type_map = {
        0: "unknown",
        1: "no_root",
        2: "removable",
        3: "fixed",
        4: "remote",
        5: "cdrom",
        6: "ramdisk",
    }

    try:
        GetDriveTypeW = ctypes.windll.kernel32.GetDriveTypeW
        # GetDriveType expects the form "Z:\"
        drive_root = drive + "\\"
        t = int(GetDriveTypeW(ctypes.c_wchar_p(drive_root)))
        return drive_type_map.get(t, "unknown")
    except Exception:
        return "unknown"


def _ps_get_disk_info_for_drive_letter(drive_letter: str) -> dict[str, Any] | None:
    """
    Best-effort: query PowerShell for disk interface details for a drive letter.
    Returns a dict or None.
    """
    drive_letter = (drive_letter or "").strip().upper()
    if not drive_letter or len(drive_letter) != 1:
        return None

    # Map drive letter -> partition -> disk -> interface model.
    ps = (
        f"$dl='{drive_letter}';"
        "try {"
        "$p = Get-Partition -DriveLetter $dl -ErrorAction Stop;"
        "$d = ($p | Get-Disk | Select-Object Number,BusType,Model,Size,PartitionStyle);"
        "if ($d) { $d | ConvertTo-Json -Compress }"
        "} catch { }"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=4,
            check=False,
        )
        stdout = (proc.stdout or "").strip()
        if not stdout:
            return None
        parsed = json.loads(stdout)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else None
        if isinstance(parsed, dict):
            return parsed
        return None
    except Exception:
        return None


def _classify_storage(
    drive_type: str, disk_info: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Translate drive/disk details into a coarse storage class and speed hint.

    Note: we intentionally provide a heuristic 'speed' because precise
    benchmarking during startup can be too expensive.
    """
    if drive_type == "remote":
        return {"storage_class": "network", "estimated_read_mb_s": 60}
    if drive_type == "removable":
        return {"storage_class": "removable", "estimated_read_mb_s": 80}
    if drive_type in ("cdrom", "ramdisk"):
        return {"storage_class": drive_type, "estimated_read_mb_s": 60}

    bus = ""
    model = ""
    if disk_info:
        bus = str(disk_info.get("BusType") or "")
        model = str(disk_info.get("Model") or "")
        # Some environments use FriendlyName/Caption; keep best-effort.
        if not model:
            model = str(disk_info.get("Caption") or "")

    bus_low = bus.lower()
    model_low = model.lower()

    if "nvme" in bus_low or "nvme" in model_low:
        return {"storage_class": "nvme", "estimated_read_mb_s": 1200}

    # Heuristic for SSD vs HDD:
    # - NVMe handled above
    # - Many SATA SSDs identify as "SSD"
    if "ssd" in model_low:
        return {"storage_class": "sata_ssd", "estimated_read_mb_s": 550}

    if "hdd" in model_low:
        return {"storage_class": "hdd", "estimated_read_mb_s": 120}

    # Fallback on bus type.
    if "sata" in bus_low:
        return {"storage_class": "sata", "estimated_read_mb_s": 250}

    return {"storage_class": "unknown", "estimated_read_mb_s": 200}


def get_storage_profile(media_root: str | None = None) -> dict[str, Any]:
    """
    Best-effort drive/storage classification for the drive behind `media_root`.

    Returns a dict with keys like:
    - drive_type: remote|fixed|removable|unknown
    - drive_letter: 'Z' or None
    - storage_class: network|hdd|sata_ssd|nvme|...
    - estimated_read_mb_s: int (heuristic)
    - disk_model: optional best-effort string
    """
    drive_type = _get_windows_drive_type(media_root or "")
    drive_letter = None
    if media_root and len(media_root) >= 2 and media_root[1] == ":":
        drive_letter = media_root[0]

    disk_info = None
    if drive_letter and drive_type not in ("remote", "unknown"):
        disk_info = _ps_get_disk_info_for_drive_letter(drive_letter)

    storage = _classify_storage(drive_type, disk_info)
    storage_class = storage.get("storage_class", "unknown")
    estimated_read_mb_s = int(storage.get("estimated_read_mb_s") or 0)

    disk_model = ""
    if disk_info:
        disk_model = str(disk_info.get("Model") or disk_info.get("Caption") or "")

    return {
        "drive_type": drive_type,
        "drive_letter": drive_letter,
        "storage_class": storage_class,
        "estimated_read_mb_s": estimated_read_mb_s,
        "disk_model": disk_model,
    }


def _round_half_up(value: float) -> int:
    return int(value + 0.5)


def _coerce_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    return number


def _load_measured_read_mb_s(media_root: str | None) -> float | None:
    try:
        from nas_checker.scan.scan_path_settings import (
            load_scan_path_settings,
            normalize_scan_path,
        )

        settings = load_scan_path_settings()
        settings_root = normalize_scan_path(settings.get("media_folder"))
        requested_root = normalize_scan_path(media_root)
        if settings_root != requested_root:
            return None
        return _coerce_positive_float(settings.get("measured_read_mb_s"))
    except Exception:
        return None


def _workers_for_measured_read_speed(
    cpu_count: int,
    measured_read_mb_s: float,
    storage_class: str,
    drive_type: str,
    confidence: str = "normal",
) -> int:
    if confidence == "low" and (storage_class == "network" or drive_type == "remote"):
        return int(max(4, min(_round_half_up(cpu_count / 2), 8)))

    # Approximate how many concurrent ffprobe reads the measured storage can feed.
    speed_limited_workers = max(2, _round_half_up(measured_read_mb_s / 15.0))
    storage_cap = 24
    if storage_class == "network" or drive_type == "remote":
        storage_cap = 16
    elif storage_class in ("hdd", "removable") or drive_type == "removable":
        storage_cap = 12
    return int(max(2, min(cpu_count, speed_limited_workers, storage_cap)))


def _iter_media_file_candidates(media_root: str) -> tuple[list[tuple[int, str]], str]:
    candidates: list[tuple[int, str]] = []
    last_error = ""
    for root, dirs, filenames in os.walk(media_root, onerror=lambda err: None):
        dirs.sort()
        for filename in sorted(filenames):
            if not filename.lower().endswith(READ_BENCHMARK_EXTENSIONS):
                continue
            file_path = os.path.join(root, filename)
            try:
                size = os.path.getsize(file_path)
            except OSError as exc:
                last_error = str(exc)
                continue
            if size <= 0:
                continue
            candidates.append((int(size), file_path))
            if len(candidates) >= 100:
                break
        if len(candidates) >= 100:
            break
    candidates.sort(reverse=True)
    return candidates, last_error


def _read_file_sample(
    handle: Any,
    file_size: int,
    target_bytes: int,
    sample_index: int,
    run_token: int = 0,
) -> int:
    if target_bytes <= 0 or file_size <= 0:
        return 0

    bytes_to_read = min(int(target_bytes), int(file_size))
    if file_size > bytes_to_read:
        # Avoid sampling only container headers; vary offsets across files and runs.
        max_offset = max(0, file_size - bytes_to_read)
        rng = random.Random((int(run_token) << 16) + int(sample_index))
        offset = rng.randint(0, max_offset)
        handle.seek(offset)

    file_read = 0
    while file_read < bytes_to_read:
        to_read = min(READ_BENCHMARK_CHUNK_BYTES, bytes_to_read - file_read)
        chunk = handle.read(to_read)
        if not chunk:
            break
        file_read += len(chunk)
    return file_read


def measure_read_throughput(
    media_root: str | None,
    max_bytes: int = DEFAULT_READ_BENCHMARK_BYTES,
    sample_count: int = DEFAULT_READ_BENCHMARK_SAMPLE_COUNT,
    run_token: int | None = None,
) -> dict[str, Any]:
    """
    Measure bounded read throughput from existing media files under `media_root`.

    The benchmark never writes to the target path. It samples up to `sample_count`
    existing media files and reads at most `max_bytes` total bytes.
    """
    result: dict[str, Any] = {
        "mb_s": 0.0,
        "bytes_read": 0,
        "elapsed_s": 0.0,
        "files_sampled": 0,
        "target_bytes": 0,
        "sample_too_small": False,
        "confidence": "low",
        "warning": "",
        "error": None,
        "message": "",
    }

    if not media_root:
        result["error"] = "missing_path"
        result["message"] = "No media folder is configured."
        return result

    try:
        max_bytes = int(max_bytes)
    except Exception:
        max_bytes = DEFAULT_READ_BENCHMARK_BYTES
    try:
        sample_count = int(sample_count)
    except Exception:
        sample_count = DEFAULT_READ_BENCHMARK_SAMPLE_COUNT
    max_bytes = max(1, max_bytes)
    sample_count = max(1, min(10, sample_count))
    if run_token is None:
        run_token = time.time_ns()
    result["target_bytes"] = int(max_bytes)

    if not os.path.isdir(media_root):
        result["error"] = "missing_path"
        result["message"] = f"Media folder does not exist: {media_root}"
        return result

    candidates, walk_error = _iter_media_file_candidates(media_root)
    if not candidates:
        result["error"] = "no_media_files"
        result["message"] = "No readable media files were found for benchmarking."
        if walk_error:
            result["message"] += f" Last error: {walk_error}"
        return result

    bytes_read = 0
    files_sampled = 0
    last_error = walk_error
    candidate_window_size = min(len(candidates), max(sample_count * 4, sample_count))
    candidate_window = list(candidates[:candidate_window_size])
    random.Random(int(run_token)).shuffle(candidate_window)
    selected_candidates = candidate_window[:sample_count]
    per_file_budget = max(
        READ_BENCHMARK_CHUNK_BYTES,
        (max_bytes + len(selected_candidates) - 1) // len(selected_candidates),
    )
    start = time.monotonic()
    for sample_index, (size, file_path) in enumerate(selected_candidates):
        if bytes_read >= max_bytes:
            break
        try:
            with open(file_path, "rb") as handle:
                file_read = _read_file_sample(
                    handle,
                    int(size),
                    min(per_file_budget, max_bytes - bytes_read),
                    sample_index,
                    int(run_token),
                )
        except OSError as exc:
            last_error = str(exc)
            continue
        if file_read:
            bytes_read += file_read
            files_sampled += 1

    elapsed_s = max(0.0, time.monotonic() - start)
    if bytes_read and elapsed_s <= 0:
        elapsed_s = 1e-9
    result["bytes_read"] = int(bytes_read)
    result["elapsed_s"] = float(elapsed_s)
    result["files_sampled"] = int(files_sampled)

    if not bytes_read or not files_sampled:
        result["error"] = "read_failed"
        result["message"] = "Media files were found, but none could be read."
        if last_error:
            result["message"] += f" Last error: {last_error}"
        return result

    mb_s = (bytes_read / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0.0
    sample_too_small = bytes_read < min(max_bytes, MIN_CONFIDENT_READ_BENCHMARK_BYTES)
    confidence = "low" if sample_too_small else "normal"
    warning = ""
    if sample_too_small:
        warning = (
            f"Sample is below {MIN_CONFIDENT_READ_BENCHMARK_BYTES / (1024 * 1024):.0f} MB; "
            "result may be affected by cache."
        )
    result["mb_s"] = float(mb_s)
    result["sample_too_small"] = bool(sample_too_small)
    result["confidence"] = confidence
    result["warning"] = warning
    result["message"] = (
        f"Read {bytes_read / (1024 * 1024):.1f} MB from {files_sampled} file(s)."
    )
    if warning:
        result["message"] += f" {warning}"
    return result


def _measured_read_confidence(
    measured_read_mb_s: float,
    storage_class: str,
    drive_type: str,
) -> tuple[float, str, str]:
    if (
        (storage_class == "network" or drive_type == "remote")
        and measured_read_mb_s > NETWORK_IMPLAUSIBLE_READ_MB_S
    ):
        return (
            NETWORK_CONSERVATIVE_READ_MB_S,
            "low",
            (
                f"network result above {NETWORK_IMPLAUSIBLE_READ_MB_S:.0f} MB/s; "
                f"using conservative {NETWORK_CONSERVATIVE_READ_MB_S:.0f} MB/s estimate"
            ),
        )
    return measured_read_mb_s, "normal", ""


def evaluate_read_benchmark_result(
    media_root: str | None,
    measured_read_mb_s: float | None,
    previous_effective_read_mb_s: float | None = None,
    benchmark_confidence: str = "normal",
) -> dict[str, Any]:
    """
    Decide which read speed is safe to persist as the effective value.

    Raw benchmark values can be dramatically inflated by OS/NAS cache on repeat
    runs. Keep the previous effective speed when a new result exceeds storage
    plausibility checks or is more than 2x the prior effective value.
    """
    raw_mb_s = _coerce_positive_float(measured_read_mb_s)
    previous_effective = _coerce_positive_float(previous_effective_read_mb_s)
    recommendation_details = get_scan_worker_recommendation(media_root, raw_mb_s)
    recommendation_confidence = recommendation_details.get("read_speed_confidence")
    benchmark_low_confidence = benchmark_confidence == "low"
    network_implausible = recommendation_confidence == "low"
    relative_implausible = (
        raw_mb_s is not None
        and previous_effective is not None
        and raw_mb_s
        > previous_effective * READ_BENCHMARK_PREVIOUS_MULTIPLIER_LIMIT
    )
    low_confidence = (
        benchmark_low_confidence or network_implausible or relative_implausible
    )

    effective_mb_s = recommendation_details.get("effective_measured_read_mb_s")
    ignored = False
    ignore_reason = ""
    if low_confidence and previous_effective is not None:
        effective_mb_s = previous_effective
        ignored = True
        ignore_reason = (
            "cached/implausible result ignored; "
            f"keeping previous effective speed {previous_effective:.0f} MB/s"
        )
    elif benchmark_low_confidence:
        effective_mb_s = previous_effective
    elif not effective_mb_s and not low_confidence:
        effective_mb_s = raw_mb_s

    return {
        "raw_mb_s": raw_mb_s,
        "effective_mb_s": effective_mb_s,
        "confidence": "low" if low_confidence else "normal",
        "ignored": ignored,
        "ignore_reason": ignore_reason,
        "recommendation_details": recommendation_details,
        "relative_implausible": relative_implausible,
        "network_implausible": network_implausible,
        "benchmark_low_confidence": benchmark_low_confidence,
    }


def get_scan_worker_recommendation(
    media_root: str | None = None, measured_read_mb_s: float | None = None
) -> dict[str, Any]:
    """
    Return a simple hardware-aware worker recommendation for ffprobe scans.

    Current scanner work is primarily `ffprobe` (CPU + storage I/O).
    GPU presence is included for visibility, but the worker count is based on
    CPU count and coarse storage class so NAS/HDD scans do not saturate I/O.
    """
    cpu_count = os.cpu_count() or 4
    has_nvidia = detect_nvidia_gpu()

    profile = get_storage_profile(media_root)
    storage_class = profile.get("storage_class", "unknown")
    drive_type = profile.get("drive_type", "unknown")
    estimated_read_mb_s = int(profile.get("estimated_read_mb_s") or 0)
    measured_read_mb_s = _coerce_positive_float(measured_read_mb_s)
    measured_source = ""
    if measured_read_mb_s is None:
        measured_read_mb_s = _load_measured_read_mb_s(media_root)
        if measured_read_mb_s is not None:
            measured_source = "settings"
    else:
        measured_source = "argument"

    raw_measured_read_mb_s = measured_read_mb_s
    effective_measured_read_mb_s = measured_read_mb_s
    measured_confidence = ""
    measured_warning = ""
    if measured_read_mb_s is not None:
        (
            effective_measured_read_mb_s,
            measured_confidence,
            measured_warning,
        ) = _measured_read_confidence(
            measured_read_mb_s, storage_class, drive_type
        )
        measured_read_mb_s = effective_measured_read_mb_s
        workers = _workers_for_measured_read_speed(
            cpu_count,
            effective_measured_read_mb_s,
            storage_class,
            drive_type,
            measured_confidence,
        )
        if measured_confidence == "low" and raw_measured_read_mb_s:
            reason = (
                f"using conservative network estimate "
                f"{effective_measured_read_mb_s:.0f} MB/s; "
                "cached/low-confidence result ignored"
            )
        else:
            reason = f"effective read speed {effective_measured_read_mb_s:.1f} MB/s"
        if storage_class == "network" or drive_type == "remote":
            reason += ": network storage tuned by benchmark"
        else:
            reason += ": storage tuned by benchmark"
        if measured_warning:
            reason += f"; {measured_warning}"
    elif storage_class == "network" or drive_type == "remote":
        workers = max(4, min(_round_half_up(cpu_count / 2), 8))
        reason = "network storage: conservative CPU/2 recommendation"
    elif storage_class in ("hdd", "removable") or drive_type == "removable":
        workers = max(4, min(_round_half_up(cpu_count / 2), 6))
        reason = "slower local/removable storage: conservative CPU/2 recommendation"
    elif storage_class == "nvme":
        workers = max(8, min(_round_half_up(cpu_count * 1.5), 24))
        reason = "NVMe storage: higher CPU-scaled recommendation"
    elif storage_class == "sata_ssd":
        workers = max(4, min(cpu_count, 12))
        reason = "SATA SSD storage: moderate CPU-scaled recommendation"
    elif storage_class == "sata":
        workers = max(4, min(cpu_count, 10))
        reason = "SATA storage: moderate CPU-scaled recommendation"
    else:
        workers = max(4, min(cpu_count, 8))
        reason = "unknown storage: moderate capped CPU recommendation"

    return {
        "workers": int(workers),
        "cpu_count": int(cpu_count),
        "storage_class": storage_class,
        "drive_type": drive_type,
        "estimated_read_mb_s": estimated_read_mb_s,
        "measured_read_mb_s": measured_read_mb_s,
        "raw_measured_read_mb_s": raw_measured_read_mb_s,
        "effective_measured_read_mb_s": effective_measured_read_mb_s,
        "read_speed_confidence": measured_confidence,
        "read_speed_warning": measured_warning,
        "read_speed_source": measured_source,
        "has_nvidia": bool(has_nvidia),
        "reason": reason,
    }


def recommend_scan_workers(
    media_root: str | None = None, measured_read_mb_s: float | None = None
) -> int:
    """Recommend a `max_workers` value for parallel scanning."""
    return int(
        get_scan_worker_recommendation(media_root, measured_read_mb_s).get("workers")
        or 4
    )
