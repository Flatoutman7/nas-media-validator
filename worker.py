from PySide6.QtCore import QThread, Signal
import main


class ScanWorker(QThread):

    progress = Signal(int, int, float, float)
    log = Signal(str)
    issue = Signal(str, str)
    finished = Signal(list)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):

        def progress_update(current, total, speed, remaining):
            self.progress.emit(current, total, speed, remaining)

        def log_update(message):
            self.log.emit(message)

        def issue_update(file, issue):
            self.issue.emit(file, issue)

        results = main.run_scan(
            self.path,
            progress_callback=progress_update,
            log_callback=log_update,
            issue_callback=issue_update
        )

        self.finished.emit(results)