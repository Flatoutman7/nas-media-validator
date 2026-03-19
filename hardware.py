import ctypes
import json
import os
import subprocess
from typing import Any, Final


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


def _classify_storage(drive_type: str, disk_info: dict[str, Any] | None) -> dict[str, Any]:
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


def recommend_scan_workers(media_root: str | None = None) -> int:
    """
    Recommend a `max_workers` value for parallel scanning.

    Current scanner work is primarily `ffprobe` (CPU + storage I/O).
    We use CPU core count, optionally NVIDIA GPU presence, and a coarse
    drive speed estimate from drive type/interface classification.
    """
    cpu_count = os.cpu_count() or 4
    has_nvidia = detect_nvidia_gpu()

    profile = get_storage_profile(media_root)
    storage_class = profile.get("storage_class", "unknown")
    estimated_read_mb_s = int(profile.get("estimated_read_mb_s") or 0)

    # Base heuristic from compute headroom.
    if has_nvidia:
        recommended = cpu_count * 2
        cap: Final[int] = 24
        min_workers: Final[int] = 6
    else:
        recommended = cpu_count
        cap = 12
        min_workers = 4

    # Apply an I/O factor based on storage class.
    # (This keeps parallel scanning from saturating slow NAS links.)
    if storage_class == "network":
        io_factor = 0.35
    elif storage_class == "hdd":
        io_factor = 0.45
    elif storage_class == "sata_ssd":
        io_factor = 0.75
    elif storage_class == "nvme":
        io_factor = 1.0
    else:
        # Unknown: be conservative.
        io_factor = 0.6

    # If we somehow got a very low speed estimate, reduce further.
    if estimated_read_mb_s and estimated_read_mb_s < 100:
        io_factor *= 0.85

    # Basic clamp.
    recommended = int(recommended * io_factor)
    recommended = max(min_workers, min(recommended, cap))
    return int(recommended)

