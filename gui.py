from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QTextEdit,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

import subprocess
import os

from worker import ScanWorker


class MainWindow(QWidget):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("NAS Media Validator")

        layout = QVBoxLayout()

        self.label = QLabel("Ready")

        self.start_button = QPushButton("Scan NAS")
        self.start_button.clicked.connect(self.start_scan)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_scan)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.stats = QLabel("Files scanned: 0 | Issues: 0 | Speed: 0/s | ETA: --")

        self.output = QTextEdit()
        self.output.setReadOnly(True)

        # --- Issue Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["File", "Issue"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 500)
        self.table.setColumnWidth(1, 300)
        self.table.cellDoubleClicked.connect(self.open_file_location)

        # ---- RIGHT CLICK MENU ----
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)

        open_action = QAction("Open File Location", self)
        open_action.triggered.connect(self.open_file_location)

        self.table.addAction(open_action)

        layout.addWidget(self.label)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.progress)
        layout.addWidget(self.stats)
        layout.addWidget(self.output)
        layout.addWidget(self.table)

        self.setLayout(layout)


    def add_issue(self, file, issue):

        # check if this file already exists in the table
        for row in range(self.table.rowCount()):

            existing_file_item = self.table.item(row, 0)

            if existing_file_item and existing_file_item.text() == file:

                issue_item = self.table.item(row, 1)

                if issue_item:
                    current_text = issue_item.text()

                    if issue not in current_text:
                        issue_item.setText(current_text + ", " + issue)

                return

        # file not yet in table → create new row
        row = self.table.rowCount()
        self.table.insertRow(row)

        file_item = QTableWidgetItem(file)
        issue_item = QTableWidgetItem(issue)

        self.table.setItem(row, 0, file_item)
        self.table.setItem(row, 1, issue_item)

        # highlight the row
        file_item.setBackground(Qt.darkRed)
        issue_item.setBackground(Qt.darkRed)

        self.table.scrollToBottom()

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

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.output.clear()
        self.table.setRowCount(0)

        self.label.setText("Scanning NAS...")

        self.worker = ScanWorker("Z:/")

        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.add_log)
        self.worker.issue.connect(self.add_issue)
        self.worker.finished.connect(self.scan_finished)

        self.worker.start()

    def stop_scan(self):
        if self.worker:
            self.worker.terminate()
        self.stop_button.setEnabled(False)    


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


    def scan_finished(self, results):

        self.start_button.setEnabled(True)

        self.label.setText("Scan Complete")

        self.output.append(f"Files with issues: {len(results)}")

        for file, issues in results:

            self.output.append(file)

            for issue in issues:
                self.output.append("  - " + issue)

            self.output.append("")