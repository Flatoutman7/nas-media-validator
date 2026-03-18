from PySide6.QtCore import QThread, Signal
import main
import threading
import os
import subprocess

from autofix import build_ffmpeg_command
from rules import analyze_file


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

        payload = main.run_scan(
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
        for input_path in self.inputs:
            issues = self.issues_by_input.get(input_path)
            if issues is None:
                # For folder mode, we re-analyze the file so the fix matches.
                issues, _stats = analyze_file(input_path)

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
                    _issues_out, stats_out = analyze_file(temp_output_path)
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
