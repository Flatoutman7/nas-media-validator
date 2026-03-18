from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QLabel,
    QProgressBar,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QMenu,
    QApplication,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

import subprocess
import os
import re

from worker import (
    AutoFixWorker,
    ScanWorker,
    SonarrRedownloadWorker,
    RadarrRedownloadWorker,
)


class MainWindow(QWidget):

    def __init__(self):

        super().__init__()
        self.worker = None
        self.resume_after = None
        self.library_stats_total = None
        self.auto_fix_worker = None
        self.sonarr_redownload_worker = None
        self.radarr_redownload_worker = None

        self.setWindowTitle("NAS Media Validator")

        main_layout = QVBoxLayout()
        self.tabs = QTabWidget()

        issues_widget = QWidget()
        issues_layout = QVBoxLayout()
        issues_widget.setLayout(issues_layout)

        stats_widget = QWidget()
        stats_layout = QVBoxLayout()
        self.library_stats_output = QTextEdit()
        self.library_stats_output.setReadOnly(True)
        self.library_stats_output.setPlaceholderText(
            "Library stats will appear here after a scan."
        )
        stats_layout.addWidget(self.library_stats_output)
        stats_widget.setLayout(stats_layout)

        self.tabs.addTab(issues_widget, "Issues")
        self.tabs.addTab(stats_widget, "Library Stats")
        main_layout.addWidget(self.tabs)

        self.label = QLabel("Ready")

        self.start_button = QPushButton("Scan NAS")
        self.start_button.clicked.connect(self.start_scan)

        self.new_scan_button = QPushButton("New Scan")
        self.new_scan_button.clicked.connect(self.start_fresh_scan)
        self.new_scan_button.setEnabled(True)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_scan)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.stats = QLabel("Files scanned: 0 | Issues: 0 | Speed: 0/s | ETA: --")

        self.output = QTextEdit()
        self.output.setReadOnly(True)

        # --- Issue Table ---
        self.issue_filter = QLineEdit()
        self.issue_filter.setPlaceholderText("Filter issues (file or issue text)...")
        self.issue_filter.setClearButtonEnabled(True)
        self.issue_filter.textChanged.connect(self.apply_issue_filter)

        self.issue_type_filter_list = QListWidget()
        self.issue_type_filter_list.setFixedHeight(260)
        self.issue_type_filter_list_label = QLabel("Issue type:")
        self.issue_type_filter_map = {
            # NOTE: input `t` is already lowercase in `apply_issue_filter()`.
            "file_small": lambda t: "file suspiciously small" in t,
            "container": lambda t: "container is not mp4" in t,
            "media_info_error": lambda t: "could not read media info" in t,
            "video_codec": lambda t: "video codec is" in t and "not hevc" in t,
            "audio_codec": lambda t: "audio codec is" in t and "not aac" in t,
            "subtitles": lambda t: "subtitle track detected" in t,
            "no_video": lambda t: "no video stream found" in t,
            "no_audio": lambda t: "no audio stream found" in t,
            "tenbit_h264": lambda t: "10bit h.264 (bad for plex)" in t,
            "pgs_subtitles": lambda t: "pgs subtitles detected" in t,
            "hdr_detected": lambda t: "hdr detected" in t,
            "multiple_commentary": lambda t: "multiple commentary tracks detected" in t,
            "multiple_audio_tracks": lambda t: "multiple audio tracks detected" in t,
            "multiple_subtitle_tracks": lambda t: "multiple subtitle tracks detected"
            in t,
            "text_subtitles": lambda t: "text subtitles detected" in t,
            "wrong_resolution": lambda t: "wrong resolution:" in t,
        }
        self.issue_type_items = [
            ("File too small", "file_small"),
            ("Container (not MP4)", "container"),
            ("Media info error", "media_info_error"),
            ("Video codec (not HEVC)", "video_codec"),
            ("Audio codec (not AAC)", "audio_codec"),
            ("Subtitles detected", "subtitles"),
            ("Missing video", "no_video"),
            ("Missing audio", "no_audio"),
            ("10bit H.264 (bad for Plex)", "tenbit_h264"),
            ("PGS subtitles", "pgs_subtitles"),
            ("HDR detected", "hdr_detected"),
            ("Multiple commentary tracks", "multiple_commentary"),
            ("Multiple audio tracks", "multiple_audio_tracks"),
            ("Multiple subtitle tracks", "multiple_subtitle_tracks"),
            ("Text subtitles (non-PGS)", "text_subtitles"),
            ("Wrong resolution", "wrong_resolution"),
        ]

        for label, issue_id in self.issue_type_items:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, issue_id)
            self.issue_type_filter_list.addItem(item)

        self.issue_type_filter_list.itemChanged.connect(
            lambda _item: self.apply_issue_filter(self.issue_filter.text())
        )

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["File", "Issue"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 500)
        self.table.setColumnWidth(1, 300)
        self.table.cellDoubleClicked.connect(self.open_file_location)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        issues_layout.addWidget(self.label)
        issues_layout.addWidget(self.start_button)
        issues_layout.addWidget(self.new_scan_button)
        issues_layout.addWidget(self.stop_button)
        issues_layout.addWidget(self.progress)
        issues_layout.addWidget(self.stats)
        issues_layout.addWidget(self.output)
        issues_layout.addWidget(self.issue_filter)
        issues_layout.addWidget(self.issue_type_filter_list_label)
        issues_layout.addWidget(self.issue_type_filter_list)
        issues_layout.addWidget(self.table)

        self.setLayout(main_layout)

    def add_issue(self, file, issue):
        file_key = self.canonicalize_path(file)
        file_disp = os.path.normpath(file) if file else file

        # check if this file already exists in the table
        for row in range(self.table.rowCount()):

            existing_file_item = self.table.item(row, 0)

            if not existing_file_item:
                continue

            # Always recompute from the visible text for stability across runs.
            # (Some rows might have a cached key created by an older normalization.)
            existing_key = self.canonicalize_path(existing_file_item.text())

            if existing_key == file_key:

                issue_item = self.table.item(row, 1)

                if issue_item:
                    current_text = issue_item.text()

                    if issue not in current_text:
                        issue_item.setText(current_text + ", " + issue)

                return

        # file not yet in table → create new row
        row = self.table.rowCount()
        self.table.insertRow(row)

        file_item = QTableWidgetItem(file_disp)
        file_item.setData(Qt.UserRole, file_key)
        issue_item = QTableWidgetItem(issue)

        self.table.setItem(row, 0, file_item)
        self.table.setItem(row, 1, issue_item)

        # highlight the row
        file_item.setBackground(Qt.darkRed)
        issue_item.setBackground(Qt.darkRed)

        self.table.scrollToBottom()
        self.apply_issue_filter(self.issue_filter.text())

    def canonicalize_path(self, file_path):
        """Return a stable key for comparing file paths across runs."""

        if not file_path:
            return ""

        # On Windows, `os.path.normcase()` only normalizes slashes and the drive
        # letter, but directory/file name casing can still differ across scans.
        # Use a full-casefolded normalized path so the same physical file stacks.
        normalized = os.path.normpath(file_path).strip()
        normalized = normalized.replace("/", "\\")
        return normalized.casefold()

    def open_folder_location(self):
        """Open Windows Explorer at the selected file's folder."""

        row = self.table.currentRow()
        if row < 0:
            return

        file_item = self.table.item(row, 0)
        if not file_item:
            return

        file_path = os.path.normpath(file_item.text())
        folder = os.path.dirname(file_path)
        if not folder:
            return

        subprocess.run(["explorer", folder], shell=True)

    def open_file_location(self):

        current_row = self.table.currentRow()

        if current_row < 0:
            return

        file_item = self.table.item(current_row, 0)

        if file_item is None:
            return

        file_path = file_item.text()

        import os
        import subprocess

        file_path = os.path.normpath(file_path)

        subprocess.run(f'explorer /select,"{file_path}"')

    def start_scan(self):
        if self.worker is not None and self.worker.isRunning():
            return

        self.start_button.setEnabled(False)
        self.new_scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        is_resume = self.resume_after is not None
        if not is_resume:
            self.output.clear()
            self.table.setRowCount(0)
            self.library_stats_total = None
            self.library_stats_output.setPlainText(
                "Library stats will be generated after the scan starts."
            )
        else:
            self.library_stats_output.setPlainText("Resuming scan... updating stats.")

        if is_resume:
            self.label.setText(f"Resuming scan...")
        else:
            self.label.setText("Scanning NAS...")

        self.worker = ScanWorker("Z:/", resume_after=self.resume_after)

        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.add_log)
        self.worker.issue.connect(self.add_issue)
        self.worker.finished.connect(self.scan_finished)

        self.worker.start()

    def start_fresh_scan(self):
        """Clear results and start a new scan from the beginning."""
        self.resume_after = None
        self.output.clear()
        self.table.setRowCount(0)
        self.library_stats_total = None
        self.library_stats_output.setPlainText(
            "Library stats will be generated after the scan starts."
        )
        self.start_scan()

    def stop_scan(self):
        """Request the current scan to stop early and update buttons."""
        if self.worker:
            self.worker.request_stop()
        self.stop_button.setEnabled(False)
        self.start_button.setEnabled(True)
        self.new_scan_button.setEnabled(True)
        self.label.setText("Stopping...")

    def show_context_menu(self, position):
        row = self.table.currentRow()
        if row < 0:
            return

        menu = QMenu()

        open_action = QAction("Open File Location", self)
        open_folder_action = QAction("Open Folder", self)
        auto_fix_file_action = QAction("Auto Fix File", self)
        auto_fix_folder_action = QAction("Auto Fix Folder", self)
        redownload_sonarr_action = QAction("Redownload Missing (Sonarr)", self)
        redownload_radarr_action = QAction("Redownload Missing (Radarr)", self)
        copy_action = QAction("Copy Path", self)
        open_action.triggered.connect(self.open_file_location)
        open_folder_action.triggered.connect(self.open_folder_location)
        auto_fix_file_action.triggered.connect(self.auto_fix_file)
        auto_fix_folder_action.triggered.connect(self.auto_fix_folder)
        redownload_sonarr_action.triggered.connect(self.redownload_missing_sonarr)
        redownload_radarr_action.triggered.connect(self.redownload_missing_radarr)
        copy_action.triggered.connect(self.copy_file_path)

        play_action = QAction("Play File", self)

        play_action.triggered.connect(self.play_file)

        menu.addAction(open_action)
        menu.addAction(open_folder_action)
        menu.addAction(auto_fix_file_action)
        menu.addAction(auto_fix_folder_action)
        menu.addAction(redownload_sonarr_action)
        menu.addAction(redownload_radarr_action)
        menu.addAction(copy_action)
        menu.addAction(play_action)

        menu.exec(self.table.viewport().mapToGlobal(position))

    def copy_file_path(self):
        row = self.table.currentRow()
        if row < 0:
            return

        file_item = self.table.item(row, 0)
        if file_item is None:
            return

        QApplication.clipboard().setText(file_item.text())

    def play_file(self):
        row = self.table.currentRow()
        if row < 0:
            return

        file_item = self.table.item(row, 0)
        if file_item is None:
            return

        os.startfile(file_item.text())

    def _selected_file_and_issues(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None

        file_item = self.table.item(row, 0)
        issue_item = self.table.item(row, 1)
        if file_item is None or issue_item is None:
            return None, None

        file_path = file_item.text()
        issues_text = issue_item.text()
        return file_path, issues_text

    def auto_fix_file(self):
        """Run ffmpeg to generate a fixed output for the selected file."""
        input_path, issues_text = self._selected_file_and_issues()
        if not input_path:
            return

        self.output.append(f"Auto-fix file: {input_path}")
        if self.auto_fix_worker and self.auto_fix_worker.isRunning():
            self.output.append("Auto-fix already running.")
            return

        self.auto_fix_worker = AutoFixWorker([input_path], {input_path: issues_text})
        self.auto_fix_worker.log.connect(self.add_log)
        self.auto_fix_worker.finished.connect(self.auto_fix_finished)
        self.auto_fix_worker.start()

    def auto_fix_folder(self):
        """Run ffmpeg auto-fix across all media files in the selected file's folder."""
        input_path, _issues_text = self._selected_file_and_issues()
        if not input_path:
            return

        folder = os.path.dirname(input_path)
        if not folder:
            return

        from scanner import MEDIA_EXTENSIONS

        media_inputs = []
        for root, _dirs, filenames in os.walk(folder):
            for name in filenames:
                if name.lower().endswith(MEDIA_EXTENSIONS):
                    media_inputs.append(os.path.join(root, name))

        if not media_inputs:
            self.output.append("No media files found in folder.")
            return

        self.output.append(f"Auto-fix folder ({len(media_inputs)} files): {folder}")

        if self.auto_fix_worker and self.auto_fix_worker.isRunning():
            self.output.append("Auto-fix already running.")
            return

        # Folder mode re-analyzes each file inside the worker.
        self.auto_fix_worker = AutoFixWorker(media_inputs)
        self.auto_fix_worker.log.connect(self.add_log)
        self.auto_fix_worker.finished.connect(self.auto_fix_finished)
        self.auto_fix_worker.start()

    def redownload_missing_sonarr(self):
        """
        Ask Sonarr to search for missing episodes for the selected series.

        This is a "request download again" action, not an in-place repair.
        """

        input_path, issues_text = self._selected_file_and_issues()
        if not input_path:
            return

        issues_lower = (issues_text or "").lower()

        missing_audio = "no audio stream found" in issues_lower
        missing_video = "no video stream found" in issues_lower
        if not (missing_audio or missing_video):
            self.output.append(
                "Redownload via Sonarr: selected row does not indicate missing audio/video."
            )
            return

        # Sonarr handles TV episodes, so we only run this for SxxEyy-like names.
        base = os.path.basename(input_path)
        if not re.search(r"\bS\d{1,2}E\d{1,2}\b", base, flags=re.IGNORECASE):
            self.output.append(
                "Redownload via Sonarr: not detected as a TV episode name (use Radarr for movies)."
            )
            return

        series_term = self.extract_media_title(input_path)
        if not series_term:
            self.output.append(
                "Redownload via Sonarr: could not extract a series name."
            )
            return

        if self.sonarr_redownload_worker and self.sonarr_redownload_worker.isRunning():
            self.output.append("Sonarr redownload already running.")
            return

        self.output.append(f"Sonarr: redownload requested for '{series_term}'")
        self.sonarr_redownload_worker = SonarrRedownloadWorker(series_term)
        self.sonarr_redownload_worker.log.connect(self.add_log)
        self.sonarr_redownload_worker.finished.connect(
            lambda msg: self.output.append(f"Sonarr: {msg}")
        )
        self.sonarr_redownload_worker.start()

    def redownload_missing_radarr(self):
        """
        Ask Radarr to search for missing movies for the selected row.

        This is intended for movie-like filenames (no SxxEyy pattern).
        """

        input_path, issues_text = self._selected_file_and_issues()
        if not input_path:
            return

        issues_lower = (issues_text or "").lower()
        missing_audio = "no audio stream found" in issues_lower
        missing_video = "no video stream found" in issues_lower
        if not (missing_audio or missing_video):
            self.output.append(
                "Redownload via Radarr: selected row does not indicate missing audio/video."
            )
            return

        base = os.path.basename(input_path)
        if re.search(r"\bS\d{1,2}E\d{1,2}\b", base, flags=re.IGNORECASE):
            self.output.append(
                "Redownload via Radarr: not detected as a movie name (use Sonarr for TV)."
            )
            return

        movie_term = self.extract_media_title(input_path)
        if not movie_term:
            self.output.append("Redownload via Radarr: could not extract movie title.")
            return

        if self.radarr_redownload_worker and self.radarr_redownload_worker.isRunning():
            self.output.append("Radarr redownload already running.")
            return

        self.output.append(f"Radarr: redownload requested for '{movie_term}'")
        self.radarr_redownload_worker = RadarrRedownloadWorker(movie_term)
        self.radarr_redownload_worker.log.connect(self.add_log)
        self.radarr_redownload_worker.finished.connect(
            lambda msg: self.output.append(f"Radarr: {msg}")
        )
        self.radarr_redownload_worker.start()

    def auto_fix_finished(self, outputs_text: str):
        """Report auto-fix output paths when the ffmpeg worker is done."""
        if outputs_text:
            self.output.append("Auto-fix outputs:")
            self.output.append(outputs_text)

    def apply_issue_filter(self, text):
        """Hide table rows that don't match the current filter text.

        Matches against file path, issue text, and a best-effort extracted show/movie title.
        """

        needle = text.strip().lower()
        selected_issue_ids = set()
        for i in range(self.issue_type_filter_list.count()):
            item = self.issue_type_filter_list.item(i)
            if item.checkState() == Qt.Checked:
                selected_issue_ids.add(item.data(Qt.UserRole))

        for row in range(self.table.rowCount()):
            file_item = self.table.item(row, 0)
            issue_item = self.table.item(row, 1)

            file_text = file_item.text() if file_item is not None else ""
            issue_text = issue_item.text() if issue_item is not None else ""
            media_title = self.extract_media_title(file_text)

            haystack = " ".join([file_text, media_title, issue_text]).lower()
            name_matches = True if not needle else needle in haystack

            issue_text_lower = issue_text.lower()
            type_matches = (
                True
                if not selected_issue_ids
                else any(
                    self.issue_type_filter_map[issue_id](issue_text_lower)
                    for issue_id in selected_issue_ids
                )
            )

            self.table.setRowHidden(row, not (name_matches and type_matches))

    def extract_media_title(self, file_path):
        """Extract a likely show/movie title from a filename.

        Example: `Show Name - S05E21 - Episode ...` -> `Show Name`
        """

        if not file_path:
            return ""

        base = os.path.basename(file_path)
        name = os.path.splitext(base)[0]

        # Common TV naming: "<Title> - S05E21 - <Episode title>"
        m = re.match(r"^(.*?)\s*-\s*S\d{1,2}E\d{1,2}\b", name, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

        # If we find an SxxExx token anywhere, take the part before it.
        m2 = re.split(r"\bS\d{1,2}E\d{1,2}\b", name, flags=re.IGNORECASE)
        if len(m2) >= 2 and m2[0].strip():
            return m2[0].rstrip(" -_.").strip()

        # Movie naming often contains a year; keep the part before it.
        m3 = re.match(r"^(.*?)(?:\s*[\(\[]\s*\d{4}\s*[\)\]]|\s*\b\d{4}\b)", name)
        if m3:
            return m3.group(1).strip()

        return name.strip()

    def update_progress(self, current, total, speed, remaining):

        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.setWindowTitle(f"NAS Media Validator — Issues: {self.table.rowCount()}")

        self.label.setText(f"Scanning {current}/{total}")
        issues = self.table.rowCount()

        eta = f"{int(remaining)}s" if remaining else "--"

        self.stats.setText(
            f"Files scanned: {current} | Issues: {issues} | Speed: {speed:.1f}/s | ETA: {eta}"
        )

    def add_log(self, message):

        self.output.append(message)

        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def scan_finished(self, payload):
        self.start_button.setEnabled(True)
        self.new_scan_button.setEnabled(True)

        bad_files = payload.get("bad_files", [])
        stats_delta = payload.get("stats", {})

        if self.library_stats_total is None:
            self.library_stats_total = self._empty_library_stats_total()

        self._merge_library_stats_delta(stats_delta)
        self._render_library_stats()

        if payload.get("cancelled"):
            self.resume_after = payload.get("resume_after")
            self.label.setText("Stopped — ready to resume")
            self.output.append(
                f"Scan stopped by user. Resume from: {self.resume_after}"
            )
            self.output.append(f"Files with issues so far: {len(bad_files)}")
            return

        self.resume_after = None
        self.label.setText("Scan Complete")

        self.output.append(f"Files with issues: {len(bad_files)}")
        for file, issues in bad_files:
            self.output.append(file)
            for issue in issues:
                self.output.append("  - " + issue)
            self.output.append("")

    def _empty_library_stats_total(self):
        return {
            "scanned_files": 0,
            "files_with_issues": 0,
            "container_not_mp4": 0,
            "video_codec_counts": {},
            "audio_codec_counts": {},
            "subtitle_tracks": 0,
            "missing_video": 0,
            "missing_audio": 0,
            "media_info_errors": 0,
            "small_files": 0,
            "hdr_detected_files": 0,
            "tenbit_h264_files": 0,
            "pgs_subtitles_files": 0,
            "multiple_commentary_files": 0,
            "wrong_resolution_files": 0,
            "multiple_audio_tracks_files": 0,
            "multiple_subtitle_tracks_files": 0,
            "text_subtitles_files": 0,
        }

    def _merge_library_stats_delta(self, delta):
        # Merge integer counters.
        for key in (
            "scanned_files",
            "files_with_issues",
            "container_not_mp4",
            "subtitle_tracks",
            "missing_video",
            "missing_audio",
            "media_info_errors",
            "small_files",
            "hdr_detected_files",
            "tenbit_h264_files",
            "pgs_subtitles_files",
            "multiple_commentary_files",
            "wrong_resolution_files",
            "multiple_audio_tracks_files",
            "multiple_subtitle_tracks_files",
            "text_subtitles_files",
        ):
            self.library_stats_total[key] += int(delta.get(key, 0) or 0)

        # Merge codec distributions.
        for codec, count in (delta.get("video_codec_counts", {}) or {}).items():
            self.library_stats_total["video_codec_counts"][codec] = (
                self.library_stats_total["video_codec_counts"].get(codec, 0)
                + int(count or 0)
            )

        for codec, count in (delta.get("audio_codec_counts", {}) or {}).items():
            self.library_stats_total["audio_codec_counts"][codec] = (
                self.library_stats_total["audio_codec_counts"].get(codec, 0)
                + int(count or 0)
            )

    def _render_library_stats(self):
        if not self.library_stats_total:
            return

        s = []
        s.append(f"Scanned files: {self.library_stats_total['scanned_files']}")
        s.append(f"Files with issues: {self.library_stats_total['files_with_issues']}")
        s.append(f"Container not MP4: {self.library_stats_total['container_not_mp4']}")
        s.append(f"Missing video stream: {self.library_stats_total['missing_video']}")
        s.append(f"Missing audio stream: {self.library_stats_total['missing_audio']}")
        s.append(
            f"Subtitle tracks found: {self.library_stats_total['subtitle_tracks']}"
        )
        s.append(f"Media info errors: {self.library_stats_total['media_info_errors']}")
        s.append(f"Suspiciously small files: {self.library_stats_total['small_files']}")
        s.append(f"HDR detected: {self.library_stats_total['hdr_detected_files']}")
        s.append(
            f"10bit H.264 detected: {self.library_stats_total['tenbit_h264_files']}"
        )
        s.append(
            f"PGS subtitles detected: {self.library_stats_total['pgs_subtitles_files']}"
        )
        s.append(
            f"Multiple commentary tracks: {self.library_stats_total['multiple_commentary_files']}"
        )
        s.append(
            f"Wrong resolution: {self.library_stats_total['wrong_resolution_files']}"
        )
        s.append(
            f"Multiple audio tracks: {self.library_stats_total['multiple_audio_tracks_files']}"
        )
        s.append(
            f"Multiple subtitle tracks: {self.library_stats_total['multiple_subtitle_tracks_files']}"
        )
        s.append(
            f"Text subtitles (non-PGS): {self.library_stats_total['text_subtitles_files']}"
        )

        def fmt_codec_counts(title, data):
            s.append("")
            s.append(title + ":")
            items = sorted(data.items(), key=lambda kv: kv[1], reverse=True)
            for codec, count in items:
                if not codec:
                    continue
                s.append(f"  {codec}: {count}")

        fmt_codec_counts(
            "Video codecs", self.library_stats_total.get("video_codec_counts", {})
        )
        fmt_codec_counts(
            "Audio codecs", self.library_stats_total.get("audio_codec_counts", {})
        )

        self.library_stats_output.setPlainText("\n".join(s))
