from PySide6.QtCore import QThread, Signal
from nas_checker.scan import main as scan_main
import threading
import os
import subprocess
import queue
import shutil

from nas_checker.media.autofix import backup_original_file, build_ffmpeg_command
from nas_checker.arr.arr_config import load_arr_config, validate_arr_service_config
from nas_checker.scan.issues import normalize_issues
from nas_checker.scan.rules import analyze_file
from nas_checker.scan.scan_rules_settings import load_scan_rules_settings
from nas_checker.arr.sonarr_client import SonarrClient
from nas_checker.arr.radarr_client import RadarrClient
from health.hardware import measure_read_throughput
from health.network_monitor import (
    measure_read_throughput_mb_s,
    measure_latency_ms,
    resolve_unc_host_from_windows_root,
)


class ScanWorker(QThread):

    progress = Signal(int, int, float, float, int, int)
    log = Signal(str)
    issue = Signal(str, str)
    finished = Signal(object)

    def __init__(self, path, resume_after=None, max_workers=None):
        super().__init__()
        self.path = path
        self.resume_after = resume_after
        self.max_workers = max_workers
        self._stop_event = threading.Event()

    def request_stop(self):
        """Signal the scan to stop early (cooperative cancellation)."""
        self._stop_event.set()

    def run(self):

        def progress_update(
            current, total, speed, remaining, cache_hits=0, cache_misses=0
        ):
            self.progress.emit(
                current, total, speed, remaining, cache_hits, cache_misses
            )

        def log_update(message):
            self.log.emit(message)

        def issue_update(file, issue):
            self.issue.emit(file, issue)

        try:
            payload = scan_main.run_scan(
                self.path,
                progress_callback=progress_update,
                log_callback=log_update,
                issue_callback=issue_update,
                resume_after=self.resume_after,
                stop_event=self._stop_event,
                max_workers=self.max_workers,
            )
        except Exception as exc:
            self.log.emit(f"Scan failed: {exc}")
            payload = {"error": str(exc), "cancelled": False}

        self.finished.emit(payload)


class ReadSpeedBenchmarkWorker(QThread):
    progress = Signal(str)
    finished = Signal(object)

    def __init__(self, path, max_bytes=None, sample_count=None):
        super().__init__()
        self.path = path
        self.max_bytes = max_bytes
        self.sample_count = sample_count

    def run(self):
        self.progress.emit("Read speed test running...")
        kwargs = {}
        if self.max_bytes is not None:
            kwargs["max_bytes"] = self.max_bytes
        if self.sample_count is not None:
            kwargs["sample_count"] = self.sample_count
        result = measure_read_throughput(self.path, **kwargs)
        self.finished.emit(result)


class ArrConnectionTestWorker(QThread):
    finished = Signal(str, bool)

    def __init__(self, service: str, base_url: str, api_key: str):
        super().__init__()
        self.service = service
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        service_config = {
            "enabled": True,
            "base_url": self.base_url,
            "api_key": self.api_key,
        }
        config_errors = validate_arr_service_config(self.service, service_config)
        label = self.service.capitalize()
        if config_errors:
            self.finished.emit(" ".join(config_errors), False)
            return

        try:
            if self.service == "sonarr":
                client = SonarrClient(base_url=self.base_url, api_key=self.api_key)
            else:
                client = RadarrClient(base_url=self.base_url, api_key=self.api_key)
            status = client._get("/api/v3/system/status")
            version = ""
            if isinstance(status, dict) and status.get("version"):
                version = f" ({status['version']})"
            self.finished.emit(f"{label} connection OK{version}.", True)
        except Exception as exc:
            self.finished.emit(f"{label} connection failed: {exc}", False)


class AutoFixWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(str)

    def __init__(self, inputs: list[str], issues_by_input=None):
        super().__init__()
        self.inputs = inputs
        self.issues_by_input = issues_by_input or {}
        self._stop_event = threading.Event()

    def request_stop(self):
        self._stop_event.set()

    def run(self):
        failures = 0
        try:
            rules_settings = load_scan_rules_settings()
            total = len(self.inputs)
            for index, input_path in enumerate(self.inputs, start=1):
                if self._stop_event.is_set():
                    break
                self.progress.emit(index - 1, total)
                try:
                    self._fix_file(input_path, rules_settings)
                except Exception as exc:
                    failures += 1
                    self.log.emit(f"Auto-fix failed: {input_path}: {exc}")
                self.progress.emit(index, total)
        except Exception as exc:
            failures += 1
            self.log.emit(f"Auto-fix failed: {exc}")
        finally:
            if self._stop_event.is_set():
                message = "Auto-fix cancelled."
            elif failures:
                message = f"Auto-fix finished with {failures} failure(s). See log."
            else:
                message = "Auto-fix finished."
            self.finished.emit(message)

    def _run_ffmpeg(self, cmd):
        # Read output separately so cancellation works even when ffmpeg is silent.
        lines = queue.Queue()
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as proc:
            def read_output():
                try:
                    for line in proc.stdout:
                        lines.put(line.rstrip("\n"))
                finally:
                    lines.put(None)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            try:
                while True:
                    if self._stop_event.is_set():
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
                    try:
                        line = lines.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    self.log.emit(line)
                return proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                reader.join()

    def _fix_file(self, input_path, rules_settings):
        issues = self.issues_by_input.get(input_path)
        if issues is None:
            issues, _stats = analyze_file(input_path, rules_settings=rules_settings)
        elif isinstance(issues, str):
            issues = [part.strip() for part in issues.split(",") if part.strip()]
        cmd, temp_output_path = build_ffmpeg_command(input_path, normalize_issues(issues))
        if cmd is None or temp_output_path is None:
            self.log.emit(f"Auto-fix: skipping (meets criteria): {input_path}")
            return

        # Container conversion must also update the extension. Never overwrite a
        # different existing media file when choosing the converted destination.
        target_ext = os.path.splitext(temp_output_path)[1]
        destination = input_path
        if os.path.splitext(input_path)[1].lower() != target_ext.lower():
            destination = os.path.splitext(input_path)[0] + target_ext
            if os.path.exists(destination):
                raise FileExistsError(f"Destination already exists: {destination}")

        self.log.emit(f"Auto-fix: {input_path}")
        self.log.emit("FFmpeg command: " + " ".join(cmd))
        try:
            returncode = self._run_ffmpeg(cmd)
            if self._stop_event.is_set():
                return
            if returncode != 0:
                raise RuntimeError(f"ffmpeg exited with {returncode}")
            _issues_out, stats_out = analyze_file(temp_output_path, rules_settings=rules_settings)
            if (stats_out.get("media_info_error") or not stats_out.get("audio_found")
                    or not stats_out.get("video_found")):
                raise RuntimeError("Output is unreadable or missing audio/video; original preserved")
            if self._stop_event.is_set():
                return
            backup_path = backup_original_file(input_path)
            if not backup_path:
                raise OSError("Backup failed; original preserved")
            self.log.emit(f"Auto-fix backup: {backup_path}")
            if destination == input_path:
                os.replace(temp_output_path, destination)
            else:
                # Exclusive creation avoids clobbering a destination created during encoding.
                with open(destination, "xb") as output:
                    try:
                        with open(temp_output_path, "rb") as source:
                            shutil.copyfileobj(source, output)
                    except Exception:
                        output.close()
                        os.remove(destination)
                        raise
                os.remove(input_path)
            self.log.emit(f"Auto-fix complete (replaced): {destination}")
        finally:
            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
            except OSError as exc:
                self.log.emit(f"Could not remove temporary output: {exc}")


class SonarrRedownloadWorker(QThread):
    log = Signal(str)
    finished = Signal(str)

    def __init__(self, series_term: str):
        super().__init__()
        self.series_term = series_term

    def run(self):
        try:
            self._redownload()
        except Exception as exc:
            self.log.emit(f"Sonarr redownload failed: {exc}")
            self.finished.emit("Sonarr redownload failed. See log.")

    def _redownload(self):
        cfg = load_arr_config()
        sonarr_cfg = (cfg or {}).get("sonarr") if cfg else None
        if not sonarr_cfg:
            self.log.emit(
                "Sonarr not configured. Create `arr_config.json` with a `sonarr` object."
            )
            self.finished.emit("Sonarr missing config.")
            return

        config_errors = validate_arr_service_config("sonarr", sonarr_cfg)
        if config_errors:
            for error in config_errors:
                self.log.emit(error)
            self.finished.emit("Sonarr config incomplete.")
            return

        base_url = sonarr_cfg.get("base_url")
        api_key = sonarr_cfg.get("api_key")
        client = SonarrClient(base_url=base_url, api_key=api_key)
        self.log.emit(f"Sonarr: looking up series for '{self.series_term}'...")
        series_id = client.find_series_id(self.series_term)
        if not series_id:
            self.log.emit("Sonarr: could not find a matching series ID.")
            self.finished.emit("No matching series.")
            return

        self.log.emit(
            f"Sonarr: triggering MissingEpisodeSearch (seriesId={series_id})..."
        )
        resp = client.missing_episode_search(series_id)
        self.log.emit(f"Sonarr response: {resp}")
        self.finished.emit("Sonarr redownload triggered.")


class RadarrRedownloadWorker(QThread):
    log = Signal(str)
    finished = Signal(str)

    def __init__(self, movie_term: str):
        super().__init__()
        self.movie_term = movie_term

    def run(self):
        try:
            self._redownload()
        except Exception as exc:
            self.log.emit(f"Radarr redownload failed: {exc}")
            self.finished.emit("Radarr redownload failed. See log.")

    def _redownload(self):
        cfg = load_arr_config()
        radarr_cfg = (cfg or {}).get("radarr") if cfg else None
        if not radarr_cfg:
            self.log.emit(
                "Radarr not configured. Create `arr_config.json` with a `radarr` object."
            )
            self.finished.emit("Radarr missing config.")
            return

        config_errors = validate_arr_service_config("radarr", radarr_cfg)
        if config_errors:
            for error in config_errors:
                self.log.emit(error)
            self.finished.emit("Radarr config incomplete.")
            return

        base_url = radarr_cfg.get("base_url")
        api_key = radarr_cfg.get("api_key")
        client = RadarrClient(base_url=base_url, api_key=api_key)
        self.log.emit(f"Radarr: looking up movie for '{self.movie_term}'...")
        movie_id = client.find_movie_id(self.movie_term)
        if not movie_id:
            self.log.emit("Radarr: could not find a matching movie ID.")
            self.finished.emit("No matching movie.")
            return

        self.log.emit(
            f"Radarr: triggering missing movie search (movieId={movie_id})..."
        )
        resp = client.missing_movie_search(movie_id)
        if isinstance(resp, dict) and "error" in resp:
            raise RuntimeError(resp["error"])
        self.log.emit(f"Radarr response: {resp}")
        self.finished.emit("Radarr redownload triggered.")


class NetworkMonitorWorker(QThread):
    measured = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        media_root: str = "Z:/",
        read_mb_per_iteration: int = 16,
        iterations: int = 5,
        min_file_bytes: int = 8 * 1024 * 1024,
    ):
        super().__init__()
        self.media_root = media_root
        self.read_mb_per_iteration = read_mb_per_iteration
        self.iterations = iterations
        self.min_file_bytes = min_file_bytes

    def run(self):
        try:
            # Latency: ping the NAS host if we can infer it from the mapped drive.
            host = resolve_unc_host_from_windows_root(self.media_root)
            latency_info = (
                measure_latency_ms(host)
                if host
                else {"latency_ms": None, "source": None}
            )
            latency_ms = latency_info.get("latency_ms")

            # Read/throughput: read a small sample window from a file under the root.
            throughput = measure_read_throughput_mb_s(
                self.media_root,
                read_mb_per_iteration=self.read_mb_per_iteration,
                iterations=self.iterations,
                min_file_bytes=self.min_file_bytes,
            )

            result = {
                "host": host,
                "latency_ms": latency_ms,
                "latency_source": latency_info.get("source"),
                "file_used": throughput.get("file_used"),
                "read_speed_mb_s": throughput.get("current_mb_s"),
                "throughput_current_mb_s": throughput.get("current_mb_s"),
                "throughput_average_mb_s": throughput.get("average_mb_s"),
                "throughput_peak_mb_s": throughput.get("peak_mb_s"),
            }
            self.measured.emit(result)
        except Exception as e:
            self.error.emit(str(e))
