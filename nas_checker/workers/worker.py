from PySide6.QtCore import QThread, Signal
from nas_checker.scan import main as scan_main
import threading
import os
import subprocess

from nas_checker.media.autofix import build_ffmpeg_command
from nas_checker.arr.arr_config import load_arr_config
from nas_checker.scan.rules import analyze_file
from nas_checker.scan.scan_rules_settings import load_scan_rules_settings
from nas_checker.arr.sonarr_client import SonarrClient
from nas_checker.arr.radarr_client import RadarrClient


class ScanWorker(QThread):

    progress = Signal(int, int, float, float)
    log = Signal(str)
    issue = Signal(str, str)
    finished = Signal(object)

    def __init__(self, path, resume_after=None):
        super().__init__()
        self.path = path
        self.resume_after = resume_after
        self._stop_event = threading.Event()

    def request_stop(self):
        """Signal the scan to stop early (cooperative cancellation)."""
        self._stop_event.set()

    def run(self):

        def progress_update(current, total, speed, remaining):
            self.progress.emit(current, total, speed, remaining)

        def log_update(message):
            self.log.emit(message)

        def issue_update(file, issue):
            self.issue.emit(file, issue)

        payload = scan_main.run_scan(
            self.path,
            progress_callback=progress_update,
            log_callback=log_update,
            issue_callback=issue_update,
            resume_after=self.resume_after,
            stop_event=self._stop_event,
        )

        self.finished.emit(payload)


class AutoFixWorker(QThread):
    log = Signal(str)
    finished = Signal(str)

    def __init__(self, inputs: list[str], issues_by_input=None):
        super().__init__()
        self.inputs = inputs
        self.issues_by_input = issues_by_input or {}

    def run(self):
        rules_settings = load_scan_rules_settings()
        for input_path in self.inputs:
            issues = self.issues_by_input.get(input_path)
            if issues is None:
                # For folder mode, we re-analyze the file so the fix matches.
                issues, _stats = analyze_file(
                    input_path, rules_settings=rules_settings
                )

            cmd, temp_output_path = build_ffmpeg_command(input_path, issues)
            if cmd is None or temp_output_path is None:
                self.log.emit(f"Auto-fix: skipping (meets criteria): {input_path}")
                continue

            self.log.emit(f"Auto-fix: {input_path}")
            self.log.emit("FFmpeg command:")
            self.log.emit(" ".join(cmd))

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log.emit(line.rstrip("\n"))
            proc.wait()

            if proc.returncode != 0:
                self.log.emit(f"Auto-fix failed (exit {proc.returncode}).")
            else:
                # Failsafe: if the generated output has no audio, do not
                # overwrite the original. This prevents "lost audio" cases.
                try:
                    _issues_out, stats_out = analyze_file(
                        temp_output_path, rules_settings=rules_settings
                    )
                    audio_found = bool(stats_out.get("audio_found"))
                except Exception:
                    # If we can't verify the output, do not overwrite the original.
                    audio_found = False

                if not audio_found:
                    self.log.emit(
                        "Auto-fix skipped overwrite: output has no audio (failsafe)."
                    )
                    try:
                        os.remove(temp_output_path)
                    except Exception:
                        pass
                else:
                    # Overwrite the original file only when ffmpeg succeeded
                    # AND the output still contains audio.
                    os.replace(temp_output_path, input_path)
                    self.log.emit(f"Auto-fix complete (replaced): {input_path}")

        self.finished.emit("Auto-fix finished.")


class SonarrRedownloadWorker(QThread):
    log = Signal(str)
    finished = Signal(str)

    def __init__(self, series_term: str):
        super().__init__()
        self.series_term = series_term

    def run(self):
        cfg = load_arr_config()
        sonarr_cfg = (cfg or {}).get("sonarr") if cfg else None
        if not sonarr_cfg:
            self.log.emit(
                "Sonarr not configured. Create `arr_config.json` with a `sonarr` object."
            )
            self.finished.emit("Sonarr missing config.")
            return

        base_url = sonarr_cfg.get("base_url")
        api_key = sonarr_cfg.get("api_key")
        if not base_url or not api_key:
            self.log.emit(
                "Sonarr config incomplete. `base_url` and `api_key` are required."
            )
            self.finished.emit("Sonarr config incomplete.")
            return

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
        cfg = load_arr_config()
        radarr_cfg = (cfg or {}).get("radarr") if cfg else None
        if not radarr_cfg:
            self.log.emit(
                "Radarr not configured. Create `arr_config.json` with a `radarr` object."
            )
            self.finished.emit("Radarr missing config.")
            return

        base_url = radarr_cfg.get("base_url")
        api_key = radarr_cfg.get("api_key")
        if not base_url or not api_key:
            self.log.emit(
                "Radarr config incomplete. `base_url` and `api_key` are required."
            )
            self.finished.emit("Radarr config incomplete.")
            return

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
        self.log.emit(f"Radarr response: {resp}")
        self.finished.emit("Radarr redownload triggered.")
