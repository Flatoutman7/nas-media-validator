from scanner import scan_folder
from rules import check_file
from concurrent.futures import ThreadPoolExecutor, as_completed
from report import save_report

MEDIA_FOLDER = "Z:/"


def run_scan(
    path=MEDIA_FOLDER, progress_callback=None, log_callback=None, issue_callback=None
):
    """Scan a folder for media files and return a list of issues found.

    Uses thread pooling for faster validation and optionally reports progress/logs/issues via callbacks.
    """

    import time
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

    def log(msg):
        """Send a message to the optional log callback."""
        if log_callback:
            log_callback(msg)

    log(f"Scanning: {path}")
    log("Checking files...")

    bad_files = []
    files_processed = 0
    total_discovered = 0

    start_time = time.time()

    def process_file(file):
        """Validate one file and return (file, issues) if any issues were found."""
        issues = check_file(file)
        if issues:
            return (file, issues)
        return None

    futures = set()

    with ThreadPoolExecutor(max_workers=32) as executor:

        for file in scan_folder(path):

            futures.add(executor.submit(process_file, file))
            total_discovered += 1

            # keep the queue from growing forever
            if len(futures) >= 64:

                done, futures = wait(futures, return_when=FIRST_COMPLETED)

                for future in done:

                    result = future.result()
                    files_processed += 1

                    if result:
                        bad_files.append(result)

                        file, issues = result

                        for issue in issues:
                            if issue_callback:
                                issue_callback(file, issue)

                    elapsed = time.time() - start_time
                    speed = files_processed / elapsed if elapsed > 0 else 0
                    remaining = (
                        (total_discovered - files_processed) / speed if speed > 0 else 0
                    )

                    if progress_callback:
                        progress_callback(
                            files_processed, total_discovered, speed, remaining
                        )

        # finish remaining futures
        for future in futures:

            result = future.result()
            files_processed += 1

            if result:
                bad_files.append(result)

                file, issues = result

                for issue in issues:
                    if issue_callback:
                        issue_callback(file, issue)

    log("")
    log("Scan complete")
    log(f"Files with issues: {len(bad_files)}")

    save_report(bad_files)

    return bad_files


if __name__ == "__main__":

    import sys

    if "--gui" in sys.argv:

        from PySide6.QtWidgets import QApplication
        from gui import MainWindow

        app = QApplication(sys.argv)

        window = MainWindow()
        window.resize(800, 600)
        window.show()

        sys.exit(app.exec())

    else:
        run_scan()
