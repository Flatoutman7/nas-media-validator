from PySide6.QtCore import QThread, Signal
import main


class ScanWorker(QThread):
    """Run scans in a background thread and emit GUI-friendly signals."""

    progress = Signal(int, int, float, float)
    log = Signal(str)
    issue = Signal(str, str)
    finished = Signal(list)

    def __init__(self, path):
        """Create a worker that will scan the given path."""
        super().__init__()
        self.path = path

    def run(self):
        """Execute the scan and emit progress/log/issue updates."""

        def progress_update(current, total, speed, remaining):
            """Forward progress updates to the GUI thread via a signal."""
            self.progress.emit(current, total, speed, remaining)

        def log_update(message):
            """Forward log messages to the GUI thread via a signal."""
            self.log.emit(message)

        def issue_update(file, issue):
            """Forward per-issue events to the GUI thread via a signal."""
            self.issue.emit(file, issue)

        results = main.run_scan(
            self.path,
            progress_callback=progress_update,
            log_callback=log_update,
            issue_callback=issue_update,
        )

        self.finished.emit(results)
