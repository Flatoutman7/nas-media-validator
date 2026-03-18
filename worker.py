from PySide6.QtCore import QThread, Signal
import main
import threading


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
