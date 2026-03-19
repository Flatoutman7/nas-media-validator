import os
import re
import subprocess
import time
import socket
from typing import Any


def resolve_unc_host_from_windows_root(root_path: str) -> str | None:
    """
    Best-effort: for mapped drives like `Z:/`, try to find the UNC host
    (e.g. `\\server\share` -> `server`) using PowerShell.

    Returns None when it can't be resolved.
    """
    if not root_path or len(root_path) < 2 or root_path[1] != ":":
        return None

    drive_letter = root_path[0].upper()

    # Approach:
    # 1) If it's an SMB mapped drive, `Get-SmbMapping` returns `RemotePath` = \\server\share.
    # 2) Fall back to Win32_LogicalDisk.ProviderName best-effort.
    ps = (
        f"$dl='{drive_letter}:';"
        "try {"
        "$m = Get-SmbMapping -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPath -eq $dl } | "
        "Select-Object -First 1;"
        "if ($m -and $m.RemotePath) { $m.RemotePath }"
        "} catch { }"
        "try {"
        f"$p = (Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='{drive_letter}:'\");"
        "if ($p -and $p.ProviderName) { $p.ProviderName }"
        "} catch { }"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            check=False,
        )
        provider = (proc.stdout or "").strip()
        if not provider:
            return None

        # Expect: \\server\share
        m = re.match(r"^\\\\([^\\]+)\\", provider)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None


def ping_latency_ms(
    host: str, count: int = 3, timeout_ms: int = 1000
) -> float | None:
    """
    Best-effort ICMP ping using Windows `ping` and parsing the output.
    """
    if not host:
        return None

    # Prefer PowerShell `Test-Connection` because it avoids localized `ping`
    # parsing issues.
    ps = (
        f"$h='{host}';"
        f"$c={int(count)};"
        "try {"
        "$r = Test-Connection -ComputerName $h -Count $c -ErrorAction SilentlyContinue;"
        "if ($r) {"
        "$avg = ($r | Measure-Object -Property ResponseTime -Average).Average;"
        "if ($avg) { $avg.TotalMilliseconds }"
        "}"
        "} catch { }"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=max(10, (timeout_ms * count) // 1000 + 5),
            check=False,
        )
        out = (proc.stdout or "").strip()
        if out:
            # PowerShell may output "12" or "0.42" depending on timing resolution.
            try:
                return float(out)
            except Exception:
                pass
    except Exception:
        pass

    # Fallback: Windows `ping` parsing (best-effort).
    try:
        proc = subprocess.run(
            ["ping", "-n", str(count), "-w", str(timeout_ms), host],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=max(10, (timeout_ms * count) // 1000 + 5),
            check=False,
        )
        out = proc.stdout or ""
        m = re.search(r"Average\s*=\s*(\d+)\s*ms", out, flags=re.I)
        if m:
            return float(m.group(1))
        m2 = re.search(r"time[=<]\s*(\d+)\s*ms", out, flags=re.I)
        if m2:
            return float(m2.group(1))
        return None
    except Exception:
        return None


def tcp_connect_latency_ms(
    host: str,
    port: int = 445,
    timeout_s: float = 2.0,
) -> int | None:
    """
    Measure latency by timing a TCP connect to `host:port` (best-effort).

    This works even when ICMP ping is blocked, as long as the service port
    (for SMB that's 445) is reachable.
    """
    if not host:
        return None

    try:
        start = time.perf_counter()
        with socket.create_connection((host, int(port)), timeout=timeout_s):
            elapsed = time.perf_counter() - start
        return int(round(elapsed * 1000.0))
    except Exception:
        return None


def measure_latency_ms(host: str) -> dict[str, Any]:
    """
    Returns:
      - latency_ms: float | None
      - source: 'icmp' | 'tcp' | None
    """
    if not host:
        return {"latency_ms": None, "source": None}

    icmp_ms = ping_latency_ms(host)
    if icmp_ms is not None:
        return {"latency_ms": icmp_ms, "source": "icmp"}

    tcp_ms = tcp_connect_latency_ms(host, port=445, timeout_s=2.0)
    if tcp_ms is not None:
        return {"latency_ms": tcp_ms, "source": "tcp"}

    return {"latency_ms": None, "source": None}


def _pick_sample_file(media_root: str, min_bytes: int = 8 * 1024 * 1024) -> str | None:
    """
    Pick a file under `media_root` to sample read performance.
    Limits traversal to reduce overhead.
    """
    if not media_root:
        return None

    # Depth limit to avoid crawling the whole NAS.
    # Accept depth 0 (root) and up to 2 levels deep.
    dirs_checked = 0
    max_dirs = 200
    for current_root, dirs, files in os.walk(media_root):
        rel = os.path.relpath(current_root, media_root)
        if rel == ".":
            depth = 0
        else:
            depth = len(rel.split(os.sep))
        dirs_checked += 1
        if dirs_checked > max_dirs:
            break

        # Don't descend further than 2 levels deep.
        if depth >= 2:
            dirs[:] = []

        for name in files:
            path = os.path.join(current_root, name)
            try:
                st = os.stat(path)
            except Exception:
                continue
            if st.st_size >= min_bytes:
                return path

    return None


def measure_read_throughput_mb_s(
    media_root: str,
    read_mb_per_iteration: int = 16,
    iterations: int = 5,
    min_file_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """
    Measure throughput by reading a small window of a sample file.

    Returns:
      - file_used
      - current_mb_s (last iteration)
      - average_mb_s
      - peak_mb_s
    """
    sample_file = _pick_sample_file(media_root, min_bytes=min_file_bytes)
    if not sample_file:
        return {"file_used": None}

    bytes_per_iter = int(read_mb_per_iteration * 1024 * 1024)
    throughputs: list[float] = []

    for i in range(iterations):
        try:
            start = time.perf_counter()
            read_bytes = 0
            with open(sample_file, "rb") as f:
                # Try to avoid reading the entire file; just read a window.
                remaining = bytes_per_iter
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    read_bytes += len(chunk)
                    remaining -= len(chunk)
            elapsed = max(time.perf_counter() - start, 1e-6)

            mb_s = (read_bytes / (1024 * 1024)) / elapsed
            throughputs.append(mb_s)
        except Exception:
            # If one iteration fails, ignore it; still report what we got.
            continue

    if not throughputs:
        return {"file_used": sample_file}

    current = throughputs[-1]
    avg = sum(throughputs) / len(throughputs)
    peak = max(throughputs)
    return {
        "file_used": sample_file,
        "current_mb_s": current,
        "average_mb_s": avg,
        "peak_mb_s": peak,
    }

