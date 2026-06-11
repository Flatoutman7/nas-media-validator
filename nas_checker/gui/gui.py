from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QLabel,
    QProgressBar,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QMenu,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QCheckBox,
    QSpinBox,
    QMessageBox,
    QGroupBox,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QAction

from datetime import date, datetime, timezone, timedelta
import json
import os
import re
import subprocess
import sys

from nas_checker.workers.worker import (
    ArrConnectionTestWorker,
    AutoFixWorker,
    ReadSpeedBenchmarkWorker,
    ScanWorker,
    SonarrRedownloadWorker,
    RadarrRedownloadWorker,
)
from nas_checker.arr.arr_config import (
    get_default_arr_config_path,
    load_arr_config,
    save_arr_config,
    validate_arr_service_config,
)
from health.scan_history import ScanHistory
from health.hardware import (
    evaluate_read_benchmark_result,
    get_scan_worker_recommendation,
    get_storage_profile,
)
from nas_checker.scan.scan_rules_settings import (
    DEFAULT_SCAN_RULES_SETTINGS,
    load_scan_rules_settings,
    save_scan_rules_settings,
)
from nas_checker.scan.scan_path_settings import (
    AUTO_FIX_MODE_AUTO_RUN,
    AUTO_FIX_MODE_OFF,
    AUTO_FIX_MODE_PROMPT,
    DEFAULT_AUTO_FIX_MODE,
    DEFAULT_AUTO_WORKERS,
    DEFAULT_MANUAL_WORKERS,
    DEFAULT_MEDIA_FOLDER,
    EFFECTIVE_READ_MB_S_KEY,
    MEASURED_READ_CONFIDENCE_KEY,
    MEASURED_READ_AT_KEY,
    MEASURED_READ_MB_S_KEY,
    RAW_MEASURED_READ_MB_S_KEY,
    get_default_scan_path_settings_path,
    load_scan_path_settings,
    normalize_auto_fix_mode,
    normalize_scan_path,
    resolve_scan_path,
    save_scan_path_settings,
)
from nas_checker.scan.preflight import format_preflight_error, run_preflight_checks
from nas_checker.scan.issues import (
    ISSUE_AUDIO_CODEC_NOT_ALLOWED,
    ISSUE_CONTAINER_NOT_ALLOWED,
    ISSUE_FILE_SMALL,
    ISSUE_HDR_DETECTED,
    ISSUE_MEDIA_INFO_ERROR,
    ISSUE_MULTIPLE_AUDIO,
    ISSUE_MULTIPLE_COMMENTARY,
    ISSUE_MULTIPLE_SUBTITLE,
    ISSUE_NO_AUDIO,
    ISSUE_NO_VIDEO,
    ISSUE_PGS_SUBTITLES,
    ISSUE_SUBTITLE_TRACK,
    ISSUE_TENBIT_H264,
    ISSUE_TEXT_SUBTITLES,
    ISSUE_VIDEO_CODEC_NOT_ALLOWED,
    ISSUE_WRONG_RESOLUTION,
    collect_issue_codes,
    issue_code,
    issue_message,
    normalize_issues,
)
from nas_checker.gui.fixes import (
    ACTION_FFMPEG,
    ACTION_RADARR,
    ACTION_SONARR,
    classify_fix_action,
    is_safe_auto_fix_action,
)
from nas_checker.output.report import save_report, save_report_json

MEDIA_SUBFOLDER_BASENAMES = {
    "show",
    "shows",
    "series",
    "tv",
    "tv shows",
    "television",
}


def _selected_root_subfolder_warning(path: str) -> str | None:
    basename = os.path.basename(os.path.normpath(path)).strip().lower()
    if basename in MEDIA_SUBFOLDER_BASENAMES:
        return (
            f"Warning: selected scan root ends with '{os.path.basename(path)}'. "
            "If you want movies and shows, choose the parent media library folder."
        )
    return None


class MainWindow(QWidget):

    def __init__(self, media_folder: str | None = None):

        super().__init__()
        self.media_folder = normalize_scan_path(media_folder or resolve_scan_path())
        self.worker = None
        self.resume_after = None
        self.resume_scan_root = None
        self.library_stats_total = None
        self.auto_fix_worker = None
        self.sonarr_redownload_worker = None
        self.radarr_redownload_worker = None
        self.arr_connection_test_workers = {}
        self.read_speed_benchmark_worker = None
        self._active_auto_fix_keys = set()
        self._pending_redownload_fixes = []
        self._active_redownload_fix_key = None
        self.current_scan_started_at: datetime | None = None
        self.scan_history = ScanHistory()
        self.cache_hits = 0
        self.cache_misses = 0
        self._overdue_prompt_shown = False
        self._scan_bad_files_by_key = {}
        self._scan_bad_files_order = []
        self._defer_fixes_refresh = False
        self._fixes_refresh_needed = False
        self._current_scan_is_resume = False
        self._suppress_auto_fix_mode_save = False
        self._fixes_select_press_state = {}

        self.setWindowTitle("NAS Media Validator")
        self._apply_app_style()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        issues_scroll = QScrollArea()
        issues_scroll.setWidgetResizable(True)
        issues_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        issues_scroll.setMinimumSize(0, 0)
        issues_widget = QWidget()
        issues_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        issues_layout = QVBoxLayout()
        issues_layout.setContentsMargins(14, 14, 14, 14)
        issues_layout.setSpacing(12)
        issues_widget.setLayout(issues_layout)

        stats_widget = QWidget()
        stats_layout = QVBoxLayout()
        stats_layout.setContentsMargins(14, 14, 14, 14)
        stats_layout.setSpacing(12)
        self.library_stats_output = QTextEdit()
        self.library_stats_output.setReadOnly(True)
        self.library_stats_output.setPlaceholderText(
            "Library stats will appear here after a scan."
        )
        stats_group = QGroupBox("Library Stats")
        stats_group_layout = QVBoxLayout(stats_group)
        stats_group_layout.setContentsMargins(16, 18, 16, 16)
        stats_group_layout.setSpacing(10)
        stats_group_layout.addWidget(self.library_stats_output)
        stats_layout.addWidget(stats_group)
        stats_widget.setLayout(stats_layout)

        issues_scroll.setWidget(issues_widget)
        fixes_scroll = self._create_fixes_tab()
        self.tabs.addTab(issues_scroll, "Scanner")
        self.tabs.addTab(fixes_scroll, "Fixes")
        self.tabs.addTab(stats_widget, "Library Stats")

        # --- Scan Settings Widget ---
        settings_widget = QScrollArea()
        settings_widget.setWidgetResizable(True)
        settings_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_widget.setMinimumSize(0, 0)
        settings_content = QWidget()
        settings_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(14)

        settings_title = QLabel("Scan Settings")
        settings_title.setProperty("role", "pageTitle")
        settings_layout.addWidget(settings_title)

        path_group = QGroupBox("Media Library")
        path_layout = QVBoxLayout(path_group)
        path_layout.setContentsMargins(16, 18, 16, 16)
        path_layout.setSpacing(10)
        path_layout.addWidget(QLabel("Media library path"))
        media_folder_row = QHBoxLayout()
        media_folder_row.setSpacing(10)
        self.scan_media_folder_edit = QLineEdit()
        self.scan_media_folder_browse_button = QPushButton("Browse...")
        self.scan_media_folder_browse_button.clicked.connect(self._browse_media_folder)
        media_folder_row.addWidget(self.scan_media_folder_edit)
        media_folder_row.addWidget(self.scan_media_folder_browse_button)
        path_layout.addLayout(media_folder_row)
        settings_layout.addWidget(path_group)
        self.scan_media_folder_edit.editingFinished.connect(
            self._update_worker_recommendation_label
        )

        self.worker_controls_group = QGroupBox("Parallel Workers / Read Speed Test")
        self.worker_controls_group.setFocusPolicy(Qt.StrongFocus)
        self.worker_controls_group.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        worker_controls_layout = QVBoxLayout(self.worker_controls_group)
        worker_controls_layout.setContentsMargins(16, 18, 16, 16)
        worker_controls_layout.setSpacing(12)

        workers_row = QHBoxLayout()
        workers_row.setSpacing(10)
        self.scan_workers_auto_checkbox = QCheckBox("Auto workers")
        self.scan_workers_auto_checkbox.setChecked(True)
        self.scan_workers_auto_checkbox.toggled.connect(self._on_auto_workers_toggled)
        self.scan_workers_manual_spin = QSpinBox()
        self.scan_workers_manual_spin.setRange(1, 64)
        self.scan_workers_manual_spin.setValue(DEFAULT_MANUAL_WORKERS)
        self.scan_workers_manual_spin.setEnabled(False)
        self.scan_workers_manual_spin.valueChanged.connect(
            self._update_worker_recommendation_label
        )
        workers_row.addWidget(self.scan_workers_auto_checkbox)
        workers_row.addWidget(QLabel("Manual workers:"))
        workers_row.addWidget(self.scan_workers_manual_spin)
        workers_row.addStretch(1)
        worker_controls_layout.addLayout(workers_row)
        self.scan_workers_recommendation_label = QLabel("Auto: detecting hardware...")
        self.scan_workers_recommendation_label.setWordWrap(True)
        self.scan_workers_recommendation_label.setProperty("role", "statusText")
        worker_controls_layout.addWidget(self.scan_workers_recommendation_label)

        worker_controls_layout.addSpacing(6)
        read_speed_row = QHBoxLayout()
        read_speed_row.setSpacing(8)
        self.read_speed_test_button = QPushButton("Test Read Speed")
        self.read_speed_test_button.setFocusPolicy(Qt.NoFocus)
        self.read_speed_test_button.setAutoDefault(False)
        self.read_speed_test_button.clicked.connect(self._start_read_speed_test)
        read_speed_row.addWidget(self.read_speed_test_button)
        read_speed_row.addStretch(1)
        worker_controls_layout.addLayout(read_speed_row)

        self.read_speed_status_label = QLabel("Read speed: not tested")
        self.read_speed_status_label.setWordWrap(True)
        self.read_speed_status_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        self.read_speed_status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.read_speed_status_label.setProperty("role", "statusText")
        worker_controls_layout.addWidget(self.read_speed_status_label)
        settings_layout.addWidget(self.worker_controls_group)

        arr_group = QGroupBox("Arr Integrations")
        arr_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        arr_layout = QVBoxLayout(arr_group)
        arr_layout.setContentsMargins(16, 18, 16, 16)
        arr_layout.setSpacing(10)
        arr_intro = QLabel(
            "Configure Sonarr and Radarr for redownload actions in the Fixes tab."
        )
        arr_intro.setWordWrap(True)
        arr_layout.addWidget(arr_intro)

        def add_arr_service_fields(service_name: str):
            service_label = service_name.capitalize()
            enabled_checkbox = QCheckBox(f"Enable {service_label}")
            arr_layout.addWidget(enabled_checkbox)

            arr_layout.addWidget(QLabel(f"{service_label} base URL"))
            base_url_edit = QLineEdit()
            base_url_edit.setPlaceholderText(
                "http://localhost:8989"
                if service_name == "sonarr"
                else "http://localhost:7878"
            )
            base_url_edit.setClearButtonEnabled(True)
            arr_layout.addWidget(base_url_edit)

            arr_layout.addWidget(QLabel(f"{service_label} API key"))
            api_key_row = QHBoxLayout()
            api_key_row.setSpacing(8)
            api_key_edit = QLineEdit()
            api_key_edit.setEchoMode(QLineEdit.Password)
            api_key_edit.setPlaceholderText(f"{service_label} API key")
            api_key_edit.setClearButtonEnabled(True)
            show_api_key_checkbox = QCheckBox("Show")
            show_api_key_checkbox.toggled.connect(
                lambda checked, edit=api_key_edit: edit.setEchoMode(
                    QLineEdit.Normal if checked else QLineEdit.Password
                )
            )
            api_key_row.addWidget(api_key_edit)
            api_key_row.addWidget(show_api_key_checkbox)
            arr_layout.addLayout(api_key_row)

            return enabled_checkbox, base_url_edit, api_key_edit, show_api_key_checkbox

        (
            self.sonarr_enabled_checkbox,
            self.sonarr_base_url_edit,
            self.sonarr_api_key_edit,
            self.sonarr_show_api_key_checkbox,
        ) = add_arr_service_fields("sonarr")

        arr_service_divider = QFrame()
        arr_service_divider.setFrameShape(QFrame.HLine)
        arr_service_divider.setFrameShadow(QFrame.Sunken)
        arr_layout.addWidget(arr_service_divider)

        (
            self.radarr_enabled_checkbox,
            self.radarr_base_url_edit,
            self.radarr_api_key_edit,
            self.radarr_show_api_key_checkbox,
        ) = add_arr_service_fields("radarr")

        arr_buttons_row = QHBoxLayout()
        arr_buttons_row.setSpacing(8)
        self.arr_save_button = QPushButton("Save Arr Settings")
        self.arr_save_button.clicked.connect(self._save_arr_settings_from_ui)
        self.sonarr_test_button = QPushButton("Test Sonarr")
        self.sonarr_test_button.clicked.connect(
            lambda: self._test_arr_connection("sonarr")
        )
        self.radarr_test_button = QPushButton("Test Radarr")
        self.radarr_test_button.clicked.connect(
            lambda: self._test_arr_connection("radarr")
        )
        arr_buttons_row.addWidget(self.arr_save_button)
        arr_buttons_row.addWidget(self.sonarr_test_button)
        arr_buttons_row.addWidget(self.radarr_test_button)
        arr_buttons_row.addStretch(1)
        arr_layout.addLayout(arr_buttons_row)

        self.arr_settings_status_label = QLabel("")
        self.arr_settings_status_label.setWordWrap(True)
        self.arr_settings_status_label.setProperty("role", "statusText")
        arr_layout.addWidget(self.arr_settings_status_label)
        settings_layout.addWidget(arr_group)

        scan_settings_divider = QFrame()
        scan_settings_divider.setFrameShape(QFrame.HLine)
        scan_settings_divider.setFrameShadow(QFrame.Sunken)
        settings_layout.addWidget(scan_settings_divider)

        scan_rules_group = QGroupBox("Scan Rule Filters")
        scan_rules_layout = QVBoxLayout(scan_rules_group)
        scan_rules_layout.setContentsMargins(16, 18, 16, 16)
        scan_rules_layout.setSpacing(10)

        def add_scan_rule_text_field(label_text: str) -> QLineEdit:
            scan_rules_layout.addWidget(QLabel(label_text))
            edit = QLineEdit()
            edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            scan_rules_layout.addWidget(edit)
            return edit

        self.scan_rules_containers_edit = add_scan_rule_text_field(
            "Containers to accept (extensions, comma-separated)"
        )

        self.scan_rules_video_codecs_edit = add_scan_rule_text_field(
            "Video codecs to accept (codec_name, comma-separated)"
        )

        self.scan_rules_audio_codecs_edit = add_scan_rule_text_field(
            "Audio codecs to accept (codec_name, comma-separated)"
        )

        scan_rules_layout.addWidget(QLabel("Minimum file size (bytes, 0 = disabled)"))
        self.scan_rules_min_size_spin = QSpinBox()
        self.scan_rules_min_size_spin.setRange(0, 2_147_483_647)
        self.scan_rules_min_size_spin.setSingleStep(100_000)
        scan_rules_layout.addWidget(self.scan_rules_min_size_spin)

        self.scan_rules_check_subtitles = QCheckBox("Flag subtitle tracks")
        self.scan_rules_check_hdr = QCheckBox("Flag HDR content")
        self.scan_rules_check_tenbit_h264 = QCheckBox("Flag 10-bit H.264")
        self.scan_rules_check_multiple_audio = QCheckBox("Flag multiple audio tracks")
        self.scan_rules_check_multiple_subtitle = QCheckBox(
            "Flag multiple subtitle tracks"
        )
        self.scan_rules_check_multiple_commentary = QCheckBox(
            "Flag multiple commentary tracks"
        )
        self.scan_rules_check_wrong_resolution = QCheckBox(
            "Flag wrong resolution vs filename"
        )
        for checkbox in (
            self.scan_rules_check_subtitles,
            self.scan_rules_check_hdr,
            self.scan_rules_check_tenbit_h264,
            self.scan_rules_check_multiple_audio,
            self.scan_rules_check_multiple_subtitle,
            self.scan_rules_check_multiple_commentary,
            self.scan_rules_check_wrong_resolution,
        ):
            scan_rules_layout.addWidget(checkbox)

        # Buttons.
        self.scan_rules_save_button = QPushButton("Save Scan Settings")
        self.scan_rules_save_button.clicked.connect(
            self._save_scan_rules_settings_from_ui
        )
        scan_rules_layout.addWidget(self.scan_rules_save_button)

        self.scan_rules_reset_button = QPushButton("Reset to Defaults")
        self.scan_rules_reset_button.clicked.connect(
            self._reset_scan_rules_settings_to_defaults
        )
        scan_rules_layout.addWidget(self.scan_rules_reset_button)

        self.scan_rules_settings_status_label = QLabel("")
        self.scan_rules_settings_status_label.setProperty("role", "statusText")
        scan_rules_layout.addWidget(self.scan_rules_settings_status_label)
        settings_layout.addWidget(scan_rules_group)

        settings_layout.addStretch(1)
        settings_widget.setWidget(settings_content)
        self.tabs.addTab(settings_widget, "Scan Settings")

        history_widget = QWidget()
        history_layout = QVBoxLayout()
        history_layout.setContentsMargins(14, 14, 14, 14)
        history_layout.setSpacing(12)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(
            [
                "Started (UTC)",
                "Status",
                "Scanned Files",
                "Files w/ Issues",
                "Issues Total",
            ]
        )
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setColumnWidth(0, 200)
        self.history_table.setColumnWidth(1, 90)
        self.history_table.setColumnWidth(2, 120)
        self.history_table.setColumnWidth(3, 120)
        self.history_table.setColumnWidth(4, 120)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.cellDoubleClicked.connect(self.load_scan_from_history)

        history_group = QGroupBox("Scan History")
        history_group_layout = QVBoxLayout(history_group)
        history_group_layout.setContentsMargins(16, 18, 16, 16)
        history_group_layout.setSpacing(10)
        history_group_layout.addWidget(self.history_table)
        history_layout.addWidget(history_group)
        history_widget.setLayout(history_layout)

        self.tabs.addTab(history_widget, "Scan History")

        # --- NAS Health Widget ---
        health_scroll = QScrollArea()
        health_scroll.setWidgetResizable(True)
        health_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        health_scroll.setMinimumSize(0, 0)
        health_widget = QWidget()
        health_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        health_layout = QVBoxLayout()
        health_layout.setContentsMargins(14, 14, 14, 14)
        health_layout.setSpacing(12)

        self.health_title = QLabel("NAS Health")
        self.health_title.setProperty("role", "pageTitle")
        health_layout.addWidget(self.health_title)

        health_overview_group = QGroupBox("Health Overview")
        health_overview_layout = QVBoxLayout(health_overview_group)
        health_overview_layout.setContentsMargins(16, 18, 16, 16)
        health_overview_layout.setSpacing(10)
        self.health_ok_progress = QProgressBar()
        self.health_ok_progress.setRange(0, 100)
        self.health_ok_progress.setValue(0)
        self.health_ok_progress.setFormat("%p%")
        health_overview_layout.addWidget(self.health_ok_progress)

        self.health_ok_label = QLabel("OK%: --")
        self.health_ok_label.setProperty("role", "statusText")
        health_overview_layout.addWidget(self.health_ok_label)
        health_layout.addWidget(health_overview_group)

        health_storage_group = QGroupBox("Storage")
        health_storage_layout = QVBoxLayout(health_storage_group)
        health_storage_layout.setContentsMargins(16, 18, 16, 16)
        health_storage_layout.setSpacing(8)
        self.health_drive_label = QLabel("Drive: --")
        self.health_storage_label = QLabel("Storage: --")
        self.health_read_speed_label = QLabel("Estimated read speed: -- MB/s")
        self.health_disk_model_label = QLabel("Disk model: --")
        health_storage_layout.addWidget(self.health_drive_label)
        health_storage_layout.addWidget(self.health_storage_label)
        health_storage_layout.addWidget(self.health_read_speed_label)
        health_storage_layout.addWidget(self.health_disk_model_label)
        health_layout.addWidget(health_storage_group)

        health_issues_group = QGroupBox("Issue Summary")
        health_issues_layout = QVBoxLayout(health_issues_group)
        health_issues_layout.setContentsMargins(16, 18, 16, 16)
        health_issues_layout.setSpacing(8)
        self.health_corrupted_label = QLabel("Corrupted Files: --")
        self.health_unreadable_label = QLabel("Unreadable: --")
        self.health_unrepairable_label = QLabel("Unrepairable: --")
        health_issues_layout.addWidget(self.health_corrupted_label)
        health_issues_layout.addWidget(self.health_unreadable_label)
        health_issues_layout.addWidget(self.health_unrepairable_label)
        health_layout.addWidget(health_issues_group)

        health_schedule_group = QGroupBox("Schedule")
        health_schedule_layout = QVBoxLayout(health_schedule_group)
        health_schedule_layout.setContentsMargins(16, 18, 16, 16)
        health_schedule_layout.setSpacing(10)
        self.health_last_scan_label = QLabel("Last Scan: --")
        self.health_next_scan_label = QLabel("Next Scan: --")
        health_schedule_layout.addWidget(self.health_last_scan_label)
        health_schedule_layout.addWidget(self.health_next_scan_label)

        self.health_overdue_label = QLabel("")
        self.health_overdue_label.setProperty("role", "dangerText")
        health_schedule_layout.addWidget(self.health_overdue_label)

        self.health_auto_start_checkbox = QCheckBox(
            "Auto-start scan when overdue on launch"
        )
        health_schedule_layout.addWidget(self.health_auto_start_checkbox)

        self.health_task_scheduler_button = QPushButton("Copy Task Scheduler command")
        self.health_task_scheduler_button.clicked.connect(
            self._copy_task_scheduler_command
        )
        health_schedule_layout.addWidget(self.health_task_scheduler_button)

        self.health_auto_start_checkbox.stateChanged.connect(
            self._on_health_auto_start_changed
        )

        # Next scan scheduling controls.
        health_schedule_layout.addWidget(QLabel("Next scan schedule:"))
        self.health_schedule_type_combo = QComboBox()
        self.health_schedule_type_combo.addItems(["Daily", "Weekly", "Custom date"])
        health_schedule_layout.addWidget(self.health_schedule_type_combo)

        self.health_weekday_combo = QComboBox()
        self.health_weekday_combo.addItems(
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ]
        )
        health_schedule_layout.addWidget(self.health_weekday_combo)

        self.health_custom_date_edit = QDateEdit()
        self.health_custom_date_edit.setCalendarPopup(True)
        health_schedule_layout.addWidget(self.health_custom_date_edit)
        health_layout.addWidget(health_schedule_group)
        health_layout.addStretch(1)

        self.health_schedule_type_combo.currentIndexChanged.connect(
            self._on_health_schedule_changed
        )
        self.health_weekday_combo.currentIndexChanged.connect(
            self._on_health_schedule_changed
        )
        self.health_custom_date_edit.dateChanged.connect(
            self._on_health_schedule_changed
        )

        health_widget.setLayout(health_layout)
        health_scroll.setWidget(health_widget)
        self.tabs.addTab(health_scroll, "NAS Health")

        self._init_scan_rules_settings_and_render()
        self._init_arr_settings_and_render()
        self._render_scan_history_table()
        self._init_health_settings_and_render()
        main_layout.addWidget(self.tabs, 1)

        self.label = QLabel("Ready")
        self.label.setProperty("role", "statusText")
        self.scan_root_label = QLabel(f"Scan root: {self.media_folder}")
        self.scan_root_label.setProperty("role", "statusText")

        self.start_button = QPushButton("Scan NAS")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self.start_scan)

        self.new_scan_button = QPushButton("New Scan")
        self.new_scan_button.clicked.connect(self.start_fresh_scan)
        self.new_scan_button.setEnabled(True)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_scan)

        export_row = QHBoxLayout()
        export_row.setSpacing(10)
        self.export_csv_button = QPushButton("Export CSV")
        self.export_json_button = QPushButton("Export JSON")
        self.export_csv_button.clicked.connect(self.export_issues_csv)
        self.export_json_button.clicked.connect(self.export_issues_json)
        export_row.addWidget(self.export_csv_button)
        export_row.addWidget(self.export_json_button)

        self.auto_fix_progress = QProgressBar()
        self.auto_fix_progress.setValue(0)
        self.auto_fix_progress.setVisible(False)
        self.auto_fix_stop_button = QPushButton("Cancel Auto-Fix")
        self.auto_fix_stop_button.setProperty("variant", "danger")
        self.auto_fix_stop_button.setVisible(False)
        self.auto_fix_stop_button.clicked.connect(self.stop_auto_fix)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.stats = QLabel("Files scanned: 0 | Issues: 0 | Speed: 0/s | ETA: --")
        self.stats.setProperty("role", "statusText")

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(150)
        self.output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        # --- Issue Table ---
        self.issue_filter = QLineEdit()
        self.issue_filter.setPlaceholderText("Filter issues (file or issue text)...")
        self.issue_filter.setClearButtonEnabled(True)
        self.issue_filter.textChanged.connect(self.apply_issue_filter)

        self.issue_type_filter_list = QListWidget()
        self.issue_type_filter_list.setMinimumHeight(120)
        self.issue_type_filter_list.setMaximumHeight(220)
        self.issue_type_filter_list.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self.issue_type_filter_list_label = QLabel("Issue type:")
        self.issue_type_filter_map = {
            ISSUE_FILE_SMALL: lambda codes: ISSUE_FILE_SMALL in codes,
            ISSUE_CONTAINER_NOT_ALLOWED: lambda codes: ISSUE_CONTAINER_NOT_ALLOWED
            in codes,
            ISSUE_MEDIA_INFO_ERROR: lambda codes: ISSUE_MEDIA_INFO_ERROR in codes,
            ISSUE_VIDEO_CODEC_NOT_ALLOWED: lambda codes: ISSUE_VIDEO_CODEC_NOT_ALLOWED
            in codes,
            ISSUE_AUDIO_CODEC_NOT_ALLOWED: lambda codes: ISSUE_AUDIO_CODEC_NOT_ALLOWED
            in codes,
            ISSUE_SUBTITLE_TRACK: lambda codes: ISSUE_SUBTITLE_TRACK in codes,
            ISSUE_NO_VIDEO: lambda codes: ISSUE_NO_VIDEO in codes,
            ISSUE_NO_AUDIO: lambda codes: ISSUE_NO_AUDIO in codes,
            ISSUE_TENBIT_H264: lambda codes: ISSUE_TENBIT_H264 in codes,
            ISSUE_PGS_SUBTITLES: lambda codes: ISSUE_PGS_SUBTITLES in codes,
            ISSUE_HDR_DETECTED: lambda codes: ISSUE_HDR_DETECTED in codes,
            ISSUE_MULTIPLE_COMMENTARY: lambda codes: ISSUE_MULTIPLE_COMMENTARY in codes,
            ISSUE_MULTIPLE_AUDIO: lambda codes: ISSUE_MULTIPLE_AUDIO in codes,
            ISSUE_MULTIPLE_SUBTITLE: lambda codes: ISSUE_MULTIPLE_SUBTITLE in codes,
            ISSUE_TEXT_SUBTITLES: lambda codes: ISSUE_TEXT_SUBTITLES in codes,
            ISSUE_WRONG_RESOLUTION: lambda codes: ISSUE_WRONG_RESOLUTION in codes,
        }
        self.issue_type_items = [
            ("File too small", ISSUE_FILE_SMALL),
            ("Container (not allowed)", ISSUE_CONTAINER_NOT_ALLOWED),
            ("Media info error", ISSUE_MEDIA_INFO_ERROR),
            ("Video codec (not allowed)", ISSUE_VIDEO_CODEC_NOT_ALLOWED),
            ("Audio codec (not allowed)", ISSUE_AUDIO_CODEC_NOT_ALLOWED),
            ("Subtitles detected", ISSUE_SUBTITLE_TRACK),
            ("Missing video", ISSUE_NO_VIDEO),
            ("Missing audio", ISSUE_NO_AUDIO),
            ("10bit H.264 (bad for Plex)", ISSUE_TENBIT_H264),
            ("PGS subtitles", ISSUE_PGS_SUBTITLES),
            ("HDR detected", ISSUE_HDR_DETECTED),
            ("Multiple commentary tracks", ISSUE_MULTIPLE_COMMENTARY),
            ("Multiple audio tracks", ISSUE_MULTIPLE_AUDIO),
            ("Multiple subtitle tracks", ISSUE_MULTIPLE_SUBTITLE),
            ("Text subtitles (non-PGS)", ISSUE_TEXT_SUBTITLES),
            ("Wrong resolution", ISSUE_WRONG_RESOLUTION),
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
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(240)
        self.table.setMaximumHeight(520)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.cellDoubleClicked.connect(self.open_file_location)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        scan_controls_group = QGroupBox("Scan Controls")
        scan_controls_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        scan_controls_layout = QVBoxLayout(scan_controls_group)
        scan_controls_layout.setContentsMargins(16, 18, 16, 16)
        scan_controls_layout.setSpacing(10)
        scan_button_row = QHBoxLayout()
        scan_button_row.setSpacing(10)
        scan_button_row.addWidget(self.start_button)
        scan_button_row.addWidget(self.new_scan_button)
        scan_button_row.addWidget(self.stop_button)
        scan_button_row.addStretch(1)
        scan_controls_layout.addWidget(self.label)
        scan_controls_layout.addWidget(self.scan_root_label)
        scan_controls_layout.addLayout(scan_button_row)
        scan_controls_layout.addLayout(export_row)
        scan_controls_layout.addWidget(self.auto_fix_progress)
        scan_controls_layout.addWidget(self.auto_fix_stop_button)
        scan_controls_layout.addWidget(self.progress)
        scan_controls_layout.addWidget(self.stats)
        issues_layout.addWidget(scan_controls_group, 0)

        scan_log_group = QGroupBox("Scan Log")
        scan_log_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        scan_log_layout = QVBoxLayout(scan_log_group)
        scan_log_layout.setContentsMargins(16, 18, 16, 16)
        scan_log_layout.setSpacing(10)
        scan_log_layout.addWidget(self.output)
        issues_layout.addWidget(scan_log_group, 0)

        issue_filters_group = QGroupBox("Issue Filters")
        issue_filters_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        issue_filters_layout = QVBoxLayout(issue_filters_group)
        issue_filters_layout.setContentsMargins(16, 18, 16, 16)
        issue_filters_layout.setSpacing(10)
        issue_filters_layout.addWidget(self.issue_filter)
        issue_filters_layout.addWidget(self.issue_type_filter_list_label)
        issue_filters_layout.addWidget(self.issue_type_filter_list)
        issues_layout.addWidget(issue_filters_group, 0)

        issues_table_group = QGroupBox("Detected Issues")
        issues_table_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        issues_table_layout = QVBoxLayout(issues_table_group)
        issues_table_layout.setContentsMargins(16, 18, 16, 16)
        issues_table_layout.setSpacing(10)
        issues_table_layout.addWidget(self.table)
        issues_layout.addWidget(issues_table_group, 1)

        self.setLayout(main_layout)
        self._apply_app_style()

        preflight_errors = run_preflight_checks(require_ffmpeg=False)
        if preflight_errors:
            QMessageBox.warning(
                self,
                "Missing dependencies",
                format_preflight_error(preflight_errors),
            )

        self._check_overdue_scan_prompt()

    def _create_fixes_tab(self) -> QScrollArea:
        fixes_scroll = QScrollArea()
        fixes_scroll.setWidgetResizable(True)
        fixes_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fixes_scroll.setMinimumSize(0, 0)

        fixes_widget = QWidget()
        fixes_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        fixes_layout = QVBoxLayout()
        fixes_layout.setContentsMargins(14, 14, 14, 14)
        fixes_layout.setSpacing(12)
        fixes_widget.setLayout(fixes_layout)

        intro_group = QGroupBox("Fix Review")
        intro_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        intro_layout = QVBoxLayout(intro_group)
        intro_layout.setContentsMargins(16, 18, 16, 16)
        intro_layout.setSpacing(10)
        intro_label = QLabel(
            "Review detected issues, select fixable rows, then run selected fixes. "
            "Nothing runs until you choose rows and click Run Selected Fixes."
        )
        intro_label.setWordWrap(True)
        self.fixes_status_label = QLabel("No issues loaded.")
        self.fixes_status_label.setProperty("role", "statusText")
        self.auto_fix_mode_combo = QComboBox()
        self.auto_fix_mode_combo.addItem("Off (default)", AUTO_FIX_MODE_OFF)
        self.auto_fix_mode_combo.addItem("Prompt after scan", AUTO_FIX_MODE_PROMPT)
        self.auto_fix_mode_combo.addItem(
            "Auto-run safe fixes after scan", AUTO_FIX_MODE_AUTO_RUN
        )
        self.auto_fix_mode_combo.currentIndexChanged.connect(
            self._on_auto_fix_mode_changed
        )
        auto_fix_mode_row = QHBoxLayout()
        auto_fix_mode_row.setSpacing(10)
        auto_fix_mode_row.addWidget(QLabel("Auto Fix after scan:"))
        auto_fix_mode_row.addWidget(self.auto_fix_mode_combo)
        auto_fix_mode_row.addStretch(1)
        self.auto_fix_mode_warning_label = QLabel(
            "Auto-run only starts ffmpeg-supported safe fixes; backups are created "
            "before replace. Redownload and manual-review items stay manual."
        )
        self.auto_fix_mode_warning_label.setWordWrap(True)
        self.auto_fix_mode_warning_label.setProperty("role", "dangerText")
        self.auto_fix_mode_status_label = QLabel("")
        self.auto_fix_mode_status_label.setProperty("role", "statusText")
        intro_layout.addWidget(intro_label)
        intro_layout.addWidget(self.fixes_status_label)
        intro_layout.addLayout(auto_fix_mode_row)
        intro_layout.addWidget(self.auto_fix_mode_warning_label)
        intro_layout.addWidget(self.auto_fix_mode_status_label)
        fixes_layout.addWidget(intro_group, 0)

        controls_group = QGroupBox("Fix Controls")
        controls_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(16, 18, 16, 16)
        controls_layout.setSpacing(10)
        self.select_all_fixes_button = QPushButton("Select All Fixable")
        self.deselect_all_fixes_button = QPushButton("Deselect All")
        self.run_selected_fixes_button = QPushButton("Run Selected Fixes")
        self.refresh_fixes_button = QPushButton("Refresh from Issues")
        self.clear_completed_fixes_button = QPushButton("Clear Completed")
        self.select_all_fixes_button.clicked.connect(self.select_all_fixable)
        self.deselect_all_fixes_button.clicked.connect(self.deselect_all_fixes)
        self.run_selected_fixes_button.clicked.connect(self.run_selected_fixes)
        self.refresh_fixes_button.clicked.connect(self.refresh_fixes_from_issues)
        self.clear_completed_fixes_button.clicked.connect(self.clear_completed_fixes)
        controls_layout.addWidget(self.select_all_fixes_button)
        controls_layout.addWidget(self.deselect_all_fixes_button)
        controls_layout.addWidget(self.run_selected_fixes_button)
        controls_layout.addWidget(self.refresh_fixes_button)
        controls_layout.addWidget(self.clear_completed_fixes_button)
        controls_layout.addStretch(1)
        fixes_layout.addWidget(controls_group, 0)

        self.fixes_table = QTableWidget()
        self.fixes_table.setColumnCount(5)
        self.fixes_table.setHorizontalHeaderLabels(
            ["Select", "File", "Issue Summary", "Available Fix", "Status"]
        )
        self.fixes_table.horizontalHeader().setStretchLastSection(True)
        self.fixes_table.setColumnWidth(0, 80)
        self.fixes_table.setColumnWidth(1, 420)
        self.fixes_table.setColumnWidth(2, 360)
        self.fixes_table.setColumnWidth(3, 190)
        self.fixes_table.setColumnWidth(4, 170)
        self.fixes_table.setAlternatingRowColors(True)
        self.fixes_table.setMinimumHeight(320)
        self.fixes_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.fixes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fixes_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.fixes_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.fixes_table.itemChanged.connect(self._on_fixes_item_changed)
        self.fixes_table.cellPressed.connect(self._on_fixes_cell_pressed)
        self.fixes_table.cellClicked.connect(self._on_fixes_cell_clicked)

        fixes_table_group = QGroupBox("Available Fixes")
        fixes_table_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        fixes_table_layout = QVBoxLayout(fixes_table_group)
        fixes_table_layout.setContentsMargins(16, 18, 16, 16)
        fixes_table_layout.setSpacing(10)
        fixes_table_layout.addWidget(self.fixes_table)
        fixes_layout.addWidget(fixes_table_group, 1)

        fixes_scroll.setWidget(fixes_widget)
        return fixes_scroll

    def _apply_app_style(self) -> None:
        app = QApplication.instance()
        if app is None:
            self.setStyleSheet(self._app_stylesheet())
            return
        app.setStyleSheet(self._app_stylesheet())

    def _app_stylesheet(self) -> str:
        return """
            QWidget {
                background: #0f172a;
                color: #e5e7eb;
                font-family: "Segoe UI", "Inter", "Arial", sans-serif;
                font-size: 10pt;
            }

            QLabel {
                color: #d7deea;
                background: transparent;
            }

            QLabel[role="pageTitle"] {
                color: #f8fafc;
                font-size: 18px;
                font-weight: 700;
                padding: 2px 0 6px 0;
            }

            QLabel[role="statusText"] {
                color: #aebbd0;
            }

            QLabel[role="dangerText"] {
                color: #f87171;
                font-weight: 700;
            }

            QTabWidget::pane {
                border: 1px solid #263348;
                border-radius: 12px;
                background: #111c2f;
                top: -1px;
            }

            QTabBar::tab {
                background: #172033;
                color: #aebbd0;
                border: 1px solid #263348;
                border-bottom: none;
                border-top-left-radius: 9px;
                border-top-right-radius: 9px;
                padding: 9px 16px;
                margin-right: 4px;
            }

            QTabBar::tab:selected {
                background: #1e2a3f;
                color: #f8fafc;
                border-color: #3b82f6;
            }

            QTabBar::tab:hover:!selected {
                background: #1b2740;
                color: #dbeafe;
            }

            QScrollArea {
                border: none;
                background: #111c2f;
            }

            QScrollArea > QWidget > QWidget {
                background: #111c2f;
            }

            QGroupBox {
                background: #172033;
                border: 1px solid #263348;
                border-radius: 14px;
                margin-top: 22px;
                padding-top: 12px;
                font-weight: 700;
                color: #f8fafc;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                top: 4px;
                padding: 3px 12px 4px 12px;
                color: #dbeafe;
                background: #172033;
                border: 1px solid #263348;
                border-radius: 9px;
            }

            QPushButton {
                background: #243149;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 9px;
                padding: 8px 14px;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #2c3a55;
                border-color: #4b5f7d;
            }

            QPushButton:pressed {
                background: #1d4ed8;
                border-color: #60a5fa;
            }

            QPushButton:disabled {
                background: #182235;
                color: #64748b;
                border-color: #253348;
            }

            QPushButton[variant="primary"] {
                background: #2563eb;
                border-color: #3b82f6;
                color: #ffffff;
            }

            QPushButton[variant="primary"]:hover {
                background: #1d4ed8;
                border-color: #60a5fa;
            }

            QPushButton[variant="danger"] {
                background: #7f1d1d;
                border-color: #991b1b;
                color: #fee2e2;
            }

            QPushButton[variant="danger"]:hover {
                background: #991b1b;
                border-color: #ef4444;
            }

            QLineEdit,
            QTextEdit,
            QComboBox,
            QDateEdit,
            QSpinBox,
            QListWidget,
            QTableWidget {
                background: #0b1220;
                color: #e5e7eb;
                border: 1px solid #334155;
                border-radius: 9px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }

            QLineEdit,
            QComboBox,
            QDateEdit,
            QSpinBox {
                min-height: 28px;
                padding: 4px 9px;
            }

            QTextEdit,
            QListWidget,
            QTableWidget {
                padding: 6px;
            }

            QLineEdit:focus,
            QTextEdit:focus,
            QComboBox:focus,
            QDateEdit:focus,
            QSpinBox:focus,
            QListWidget:focus,
            QTableWidget:focus {
                border-color: #60a5fa;
            }

            QLineEdit:disabled,
            QComboBox:disabled,
            QDateEdit:disabled,
            QSpinBox:disabled {
                background: #121a2b;
                color: #64748b;
            }

            QComboBox::drop-down,
            QDateEdit::drop-down,
            QSpinBox::up-button,
            QSpinBox::down-button {
                border: none;
                background: #1e293b;
                width: 22px;
                border-radius: 5px;
            }

            QComboBox QAbstractItemView {
                background: #0b1220;
                color: #e5e7eb;
                border: 1px solid #334155;
                selection-background-color: #2563eb;
            }

            QCheckBox {
                spacing: 8px;
                color: #d7deea;
                background: transparent;
            }

            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #64748b;
                background: #0b1220;
            }

            QCheckBox::indicator:hover {
                border-color: #60a5fa;
            }

            QCheckBox::indicator:checked {
                background: #16a34a;
                border-color: #22c55e;
            }

            QProgressBar {
                background: #0b1220;
                color: #dbeafe;
                border: 1px solid #334155;
                border-radius: 9px;
                min-height: 20px;
                text-align: center;
                font-weight: 600;
            }

            QProgressBar::chunk {
                background: #2563eb;
                border-radius: 8px;
            }

            QHeaderView::section {
                background: #1e293b;
                color: #dbeafe;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 1px solid #334155;
                padding: 7px 9px;
                font-weight: 700;
            }

            QTableWidget {
                gridline-color: #233047;
                alternate-background-color: #111827;
            }

            QTableWidget::item,
            QListWidget::item {
                padding: 6px;
            }

            QTableWidget::item:selected,
            QListWidget::item:selected {
                background: #2563eb;
                color: #ffffff;
            }

            QTableWidget::item:selected:!active,
            QListWidget::item:selected:!active {
                background: #1d4ed8;
                color: #ffffff;
            }

            QTableWidget::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #64748b;
                background: #0b1220;
            }

            QTableWidget::indicator:hover {
                border-color: #60a5fa;
            }

            QTableWidget::indicator:checked {
                background: #16a34a;
                border-color: #22c55e;
            }

            QMenu {
                background: #111827;
                color: #e5e7eb;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
            }

            QMenu::item {
                padding: 7px 24px 7px 12px;
                border-radius: 6px;
            }

            QMenu::item:selected {
                background: #2563eb;
                color: #ffffff;
            }

            QFrame[frameShape="4"],
            QFrame[frameShape="5"] {
                color: #263348;
            }

            QScrollBar:vertical {
                background: #0b1220;
                width: 12px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background: #334155;
                border-radius: 6px;
                min-height: 24px;
            }

            QScrollBar::handle:vertical:hover {
                background: #475569;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
                height: 0;
            }
        """

    def _reset_current_scan_bad_files_model(self) -> None:
        self._scan_bad_files_by_key = {}
        self._scan_bad_files_order = []

    def _record_current_scan_issue(self, file, issue) -> None:
        file_key = self.canonicalize_path(file)
        if not file_key:
            return

        file_disp = os.path.normpath(file) if file else file
        normalized_issue = normalize_issues([issue])[0]
        issue_identity = (
            normalized_issue.get("code"),
            normalized_issue.get("message"),
        )

        entry = self._scan_bad_files_by_key.get(file_key)
        if entry is None:
            entry = {"file": file_disp, "issues": [], "_issue_identities": set()}
            self._scan_bad_files_by_key[file_key] = entry
            self._scan_bad_files_order.append(file_key)

        if issue_identity not in entry["_issue_identities"]:
            entry["issues"].append(normalized_issue)
            entry["_issue_identities"].add(issue_identity)

    def _normalized_bad_file_entries(self, bad_files) -> list[dict]:
        entries: list[dict] = []
        for entry in bad_files or []:
            if isinstance(entry, dict):
                file_path = entry.get("file")
                issues = entry.get("issues") or []
            else:
                try:
                    file_path, issues = entry
                except (TypeError, ValueError):
                    continue

            if not file_path:
                continue

            if isinstance(issues, str):
                issues = [s.strip() for s in issues.split(",") if s.strip()]
            normalized_issues = normalize_issues(issues)
            if not normalized_issues:
                continue

            entries.append(
                {
                    "file": os.path.normpath(str(file_path)),
                    "issues": normalized_issues,
                }
            )

        return entries

    def _merge_bad_file_entries_into_current_scan(self, bad_files) -> None:
        for entry in self._normalized_bad_file_entries(bad_files):
            for issue in entry["issues"]:
                self._record_current_scan_issue(entry["file"], issue)

    def _current_scan_bad_files_snapshot(self) -> list[dict]:
        snapshot: list[dict] = []
        for file_key in self._scan_bad_files_order:
            entry = self._scan_bad_files_by_key.get(file_key)
            if not entry:
                continue
            issues = normalize_issues(entry.get("issues") or [])
            if not issues:
                continue
            snapshot.append({"file": entry.get("file"), "issues": issues})
        return snapshot

    def _bad_files_issue_count(self, bad_files: list[dict]) -> int:
        return sum(len(entry.get("issues") or []) for entry in bad_files)

    def _schedule_fixes_refresh(self, preserve_state: bool = True) -> None:
        if self._defer_fixes_refresh:
            self._fixes_refresh_needed = True
            return
        self.refresh_fixes_from_issues(preserve_state=preserve_state)

    def add_issue(self, file, issue):
        file_key = self.canonicalize_path(file)
        file_disp = os.path.normpath(file) if file else file
        issue_text = issue_message(issue)
        self._record_current_scan_issue(file, issue)

        # check if this file already exists in the table
        for row in range(self.table.rowCount()):

            existing_file_item = self.table.item(row, 0)

            if not existing_file_item:
                continue

            existing_key = self.canonicalize_path(existing_file_item.text())

            if existing_key == file_key:

                issue_item = self.table.item(row, 1)

                if issue_item:
                    current_text = issue_item.text()

                    if issue_text not in current_text:
                        issue_item.setText(current_text + ", " + issue_text)

                self._schedule_fixes_refresh(preserve_state=True)
                return

        # file not yet in table → create new row
        row = self.table.rowCount()
        self.table.insertRow(row)

        file_item = QTableWidgetItem(file_disp)
        file_item.setData(Qt.UserRole, file_key)
        issue_item = QTableWidgetItem(issue_text)

        self.table.setItem(row, 0, file_item)
        self.table.setItem(row, 1, issue_item)

        # highlight the row
        file_item.setBackground(Qt.darkRed)
        issue_item.setBackground(Qt.darkRed)

        self.table.scrollToBottom()
        self.apply_issue_filter(self.issue_filter.text())
        self._schedule_fixes_refresh(preserve_state=True)

    def _on_fixes_item_changed(self, item):
        if getattr(self, "_suppress_fixes_item_changed", False):
            return
        if item.column() == 0:
            self._update_fixes_status_label()

    def _on_fixes_cell_pressed(self, row: int, column: int) -> None:
        if column != 0:
            return
        select_item = self.fixes_table.item(row, 0)
        if self._is_fix_row_checkable(row, select_item):
            self._fixes_select_press_state[row] = select_item.checkState()
        else:
            self._fixes_select_press_state.pop(row, None)

    def _on_fixes_cell_clicked(self, row: int, column: int) -> None:
        if row < 0:
            return
        self.fixes_table.selectRow(row)
        if column == 0:
            pressed_state = self._fixes_select_press_state.pop(row, None)
            self._toggle_fix_row_checked(row, only_if_unchanged_from=pressed_state)
            return
        self._toggle_fix_row_checked(row)

    def _is_fix_row_checkable(self, row: int, select_item=None) -> bool:
        entry = self._fix_entry_for_row(row)
        if not entry or not entry.get("fixable"):
            return False
        select_item = select_item or self.fixes_table.item(row, 0)
        return bool(select_item and select_item.flags() & Qt.ItemIsEnabled)

    def _toggle_fix_row_checked(
        self, row: int, only_if_unchanged_from: Qt.CheckState | None = None
    ) -> None:
        select_item = self.fixes_table.item(row, 0)
        if not self._is_fix_row_checkable(row, select_item):
            return
        if (
            only_if_unchanged_from is not None
            and select_item.checkState() != only_if_unchanged_from
        ):
            self._update_fixes_status_label()
            return
        next_state = (
            Qt.Unchecked if select_item.checkState() == Qt.Checked else Qt.Checked
        )
        select_item.setCheckState(next_state)

    def _current_fixes_state(self) -> dict[str, dict]:
        state = {}
        if not hasattr(self, "fixes_table"):
            return state
        for row in range(self.fixes_table.rowCount()):
            file_item = self.fixes_table.item(row, 1)
            select_item = self.fixes_table.item(row, 0)
            status_item = self.fixes_table.item(row, 4)
            if file_item is None:
                continue
            file_key = file_item.data(Qt.UserRole) or self.canonicalize_path(
                file_item.text()
            )
            state[file_key] = {
                "checked": select_item.checkState() if select_item else Qt.Unchecked,
                "status": status_item.text() if status_item else "",
            }
        return state

    def refresh_fixes_from_issues(self, preserve_state: bool = True) -> None:
        if not hasattr(self, "fixes_table"):
            return

        previous_state = self._current_fixes_state() if preserve_state else {}
        issue_rows = []
        for issue_row in range(self.table.rowCount()):
            file_item = self.table.item(issue_row, 0)
            issue_item = self.table.item(issue_row, 1)
            if file_item is None or issue_item is None:
                continue
            issue_rows.append((file_item.text(), issue_item.text()))

        self._suppress_fixes_item_changed = True
        self.fixes_table.setUpdatesEnabled(False)
        try:
            self.fixes_table.setRowCount(len(issue_rows))
            for row, (file_path, issues_text) in enumerate(issue_rows):
                file_key = self.canonicalize_path(file_path)
                action = classify_fix_action(file_path, issues_text)
                previous = previous_state.get(file_key, {})
                checked = (
                    previous.get("checked", Qt.Unchecked)
                    if action.fixable
                    else Qt.Unchecked
                )
                status = previous.get("status") or action.status
                if is_safe_auto_fix_action(action) and status == "Ready":
                    status = "Ready - safe auto-fix eligible"
                if file_key in self._active_auto_fix_keys:
                    status = "Running ffmpeg"
                elif self._active_redownload_fix_key == file_key:
                    status = "Running redownload"

                select_item = QTableWidgetItem("")
                select_item.setFlags(
                    Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
                )
                select_item.setCheckState(checked)
                if not action.fixable:
                    select_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                    select_item.setToolTip(
                        "Manual review required; no automatic fix is available."
                    )

                file_fix_item = QTableWidgetItem(file_path)
                file_fix_item.setData(Qt.UserRole, file_key)
                issue_summary_item = QTableWidgetItem(issues_text)
                fix_label = action.label
                if is_safe_auto_fix_action(action):
                    fix_label = f"{action.label} (safe auto-fix eligible)"
                fix_item = QTableWidgetItem(fix_label)
                fix_item.setData(
                    Qt.UserRole,
                    {
                        "file_key": file_key,
                        "file_path": file_path,
                        "issues_text": issues_text,
                        "action_id": action.action_id,
                        "fixable": action.fixable,
                        "auto_fix_eligible": action.auto_fix_eligible,
                        "label": action.label,
                    },
                )
                status_item = QTableWidgetItem(status)

                for item in (
                    file_fix_item,
                    issue_summary_item,
                    fix_item,
                    status_item,
                ):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setToolTip(item.text())

                self.fixes_table.setItem(row, 0, select_item)
                self.fixes_table.setItem(row, 1, file_fix_item)
                self.fixes_table.setItem(row, 2, issue_summary_item)
                self.fixes_table.setItem(row, 3, fix_item)
                self.fixes_table.setItem(row, 4, status_item)
        finally:
            self.fixes_table.setUpdatesEnabled(True)
            self._suppress_fixes_item_changed = False

        self._update_fixes_status_label()

    def _update_fixes_status_label(self) -> None:
        if not hasattr(self, "fixes_status_label"):
            return

        total = self.fixes_table.rowCount()
        fixable = 0
        auto_fix_eligible = 0
        selected = 0
        for row in range(total):
            entry = self._fix_entry_for_row(row)
            if entry and entry.get("fixable"):
                fixable += 1
            if entry and entry.get("auto_fix_eligible"):
                auto_fix_eligible += 1
            select_item = self.fixes_table.item(row, 0)
            if select_item and select_item.checkState() == Qt.Checked:
                selected += 1

        self.fixes_status_label.setText(
            f"Rows: {total} | Fixable: {fixable} | "
            f"Safe auto-fix eligible: {auto_fix_eligible} | Selected: {selected}"
        )
        self._update_auto_fix_mode_label()

    def _fix_entry_for_row(self, row: int) -> dict | None:
        fix_item = self.fixes_table.item(row, 3)
        if fix_item is None:
            return None
        entry = fix_item.data(Qt.UserRole)
        return entry if isinstance(entry, dict) else None

    def _set_fix_status_by_key(self, file_key: str, status: str) -> None:
        if not file_key or not hasattr(self, "fixes_table"):
            return
        for row in range(self.fixes_table.rowCount()):
            file_item = self.fixes_table.item(row, 1)
            if file_item is None:
                continue
            row_key = file_item.data(Qt.UserRole) or self.canonicalize_path(
                file_item.text()
            )
            if row_key == file_key:
                status_item = self.fixes_table.item(row, 4)
                if status_item is not None:
                    status_item.setText(status)
                break

    def _current_auto_fix_mode(self) -> str:
        if hasattr(self, "auto_fix_mode_combo"):
            mode = self.auto_fix_mode_combo.currentData()
        else:
            mode = getattr(self, "scan_path_settings", {}).get("auto_fix_mode")
        return normalize_auto_fix_mode(mode)

    def _set_auto_fix_mode_combo(self, mode: str) -> None:
        if not hasattr(self, "auto_fix_mode_combo"):
            return
        normalized_mode = normalize_auto_fix_mode(mode)
        index = self.auto_fix_mode_combo.findData(normalized_mode)
        if index < 0:
            index = self.auto_fix_mode_combo.findData(DEFAULT_AUTO_FIX_MODE)
        self._suppress_auto_fix_mode_save = True
        try:
            self.auto_fix_mode_combo.setCurrentIndex(max(index, 0))
        finally:
            self._suppress_auto_fix_mode_save = False
        self._update_auto_fix_mode_label()

    def _auto_fix_mode_display_name(self, mode: str | None = None) -> str:
        mode = normalize_auto_fix_mode(mode or self._current_auto_fix_mode())
        labels = {
            AUTO_FIX_MODE_OFF: "Off",
            AUTO_FIX_MODE_PROMPT: "Prompt after scan",
            AUTO_FIX_MODE_AUTO_RUN: "Auto-run safe fixes after scan",
        }
        return labels.get(mode, labels[AUTO_FIX_MODE_OFF])

    def _update_auto_fix_mode_label(self) -> None:
        if not hasattr(self, "auto_fix_mode_status_label"):
            return
        self.auto_fix_mode_status_label.setText(
            f"Current auto-fix mode: {self._auto_fix_mode_display_name()}."
        )

    def _on_auto_fix_mode_changed(self, _index: int) -> None:
        mode = self._current_auto_fix_mode()
        self._update_auto_fix_mode_label()
        if getattr(self, "_suppress_auto_fix_mode_save", False):
            return
        if hasattr(self, "scan_path_settings_path"):
            save_scan_path_settings(
                {
                    "media_folder": normalize_scan_path(
                        self.scan_media_folder_edit.text()
                    ),
                    "auto_fix_mode": mode,
                },
                self.scan_path_settings_path,
            )
            self.scan_path_settings = load_scan_path_settings(
                self.scan_path_settings_path
            )
        self.output.append(
            f"Auto Fix mode set to {self._auto_fix_mode_display_name(mode)}."
        )

    def _safe_auto_fix_entries_from_table(self) -> list[dict]:
        entries = []
        seen_file_keys = set()
        if not hasattr(self, "fixes_table"):
            return entries
        for row in range(self.fixes_table.rowCount()):
            entry = self._fix_entry_for_row(row)
            if not entry or not entry.get("auto_fix_eligible"):
                continue
            if entry.get("action_id") != ACTION_FFMPEG:
                continue
            file_key = entry.get("file_key")
            if not file_key or file_key in seen_file_keys:
                continue
            seen_file_keys.add(file_key)
            entries.append(entry)
        return entries

    def _start_ffmpeg_auto_fix_entries(
        self, entries: list[dict], source_label: str = "Fixes"
    ) -> bool:
        if self.auto_fix_worker and self.auto_fix_worker.isRunning():
            self.output.append(f"{source_label}: auto-fix already running.")
            return False
        if not entries:
            self.output.append(f"{source_label}: no safe ffmpeg fixes to run.")
            return False

        inputs = [entry["file_path"] for entry in entries]
        issues_by_input = {
            entry["file_path"]: entry["issues_text"] for entry in entries
        }
        self._active_auto_fix_keys = {entry["file_key"] for entry in entries}
        for entry in entries:
            self._set_fix_status_by_key(entry["file_key"], "Running ffmpeg")

        self.output.append(
            f"{source_label}: running ffmpeg auto-fix for {len(inputs)} file(s)."
        )
        self.auto_fix_worker = AutoFixWorker(inputs, issues_by_input)
        self.auto_fix_worker.log.connect(self.add_log)
        self.auto_fix_worker.progress.connect(self.update_auto_fix_progress)
        self.auto_fix_worker.finished.connect(self.auto_fix_finished)
        self.auto_fix_progress.setVisible(True)
        self.auto_fix_progress.setMaximum(len(inputs))
        self.auto_fix_progress.setValue(0)
        self.auto_fix_stop_button.setVisible(True)
        self.auto_fix_stop_button.setEnabled(True)
        self.auto_fix_worker.start()
        return True

    def select_all_fixable(self) -> None:
        self._suppress_fixes_item_changed = True
        try:
            for row in range(self.fixes_table.rowCount()):
                entry = self._fix_entry_for_row(row)
                select_item = self.fixes_table.item(row, 0)
                if (
                    entry
                    and entry.get("fixable")
                    and select_item is not None
                    and select_item.flags() & Qt.ItemIsEnabled
                ):
                    select_item.setCheckState(Qt.Checked)
        finally:
            self._suppress_fixes_item_changed = False
        self._update_fixes_status_label()

    def deselect_all_fixes(self) -> None:
        self._suppress_fixes_item_changed = True
        try:
            for row in range(self.fixes_table.rowCount()):
                select_item = self.fixes_table.item(row, 0)
                if select_item is not None:
                    select_item.setCheckState(Qt.Unchecked)
        finally:
            self._suppress_fixes_item_changed = False
        self._update_fixes_status_label()

    def clear_completed_fixes(self) -> None:
        for row in range(self.fixes_table.rowCount() - 1, -1, -1):
            status_item = self.fixes_table.item(row, 4)
            status = status_item.text().lower() if status_item else ""
            if status.startswith("finished") or status.startswith(
                "redownload requested"
            ):
                self.fixes_table.removeRow(row)
        self._update_fixes_status_label()

    def run_selected_fixes(self) -> None:
        if self.auto_fix_worker and self.auto_fix_worker.isRunning():
            self.output.append("Fixes: auto-fix already running.")
            return
        if self.sonarr_redownload_worker and self.sonarr_redownload_worker.isRunning():
            self.output.append("Fixes: Sonarr redownload already running.")
            return
        if self.radarr_redownload_worker and self.radarr_redownload_worker.isRunning():
            self.output.append("Fixes: Radarr redownload already running.")
            return

        selected_entries = []
        seen_file_keys = set()
        for row in range(self.fixes_table.rowCount()):
            select_item = self.fixes_table.item(row, 0)
            if select_item is None or select_item.checkState() != Qt.Checked:
                continue
            entry = self._fix_entry_for_row(row)
            if not entry or not entry.get("fixable"):
                continue
            file_key = entry.get("file_key")
            if not file_key or file_key in seen_file_keys:
                continue
            seen_file_keys.add(file_key)
            selected_entries.append(entry)

        if not selected_entries:
            self.output.append("Fixes: no fixable rows selected.")
            return

        ffmpeg_entries = [
            entry
            for entry in selected_entries
            if entry.get("action_id") == ACTION_FFMPEG
        ]
        redownload_entries = [
            entry
            for entry in selected_entries
            if entry.get("action_id") in {ACTION_SONARR, ACTION_RADARR}
        ]

        if ffmpeg_entries:
            self._start_ffmpeg_auto_fix_entries(ffmpeg_entries, "Fixes")

        self._pending_redownload_fixes = list(redownload_entries)
        self._start_next_redownload_fix()
        self._update_fixes_status_label()

    def _start_next_redownload_fix(self) -> None:
        if self._active_redownload_fix_key is not None:
            return
        if not self._pending_redownload_fixes:
            return

        entry = self._pending_redownload_fixes.pop(0)
        file_path = entry.get("file_path") or ""
        file_key = entry.get("file_key") or self.canonicalize_path(file_path)
        media_term = self.extract_media_title(file_path)
        if not media_term:
            self._set_fix_status_by_key(file_key, "Error: title not found")
            self._start_next_redownload_fix()
            return

        self._active_redownload_fix_key = file_key
        self._set_fix_status_by_key(file_key, "Running redownload")

        action_id = entry.get("action_id")
        if action_id == ACTION_SONARR:
            if not self._arr_service_ready_for_redownload("sonarr"):
                self._set_fix_status_by_key(file_key, "Error: Sonarr not configured")
                self._active_redownload_fix_key = None
                self._start_next_redownload_fix()
                return
            self.output.append(f"Fixes: Sonarr redownload requested for '{media_term}'")
            self.sonarr_redownload_worker = SonarrRedownloadWorker(media_term)
            self.sonarr_redownload_worker.log.connect(self.add_log)
            self.sonarr_redownload_worker.finished.connect(
                lambda msg, key=file_key: self._redownload_fix_finished(key, msg)
            )
            self.sonarr_redownload_worker.start()
            return

        if action_id == ACTION_RADARR:
            if not self._arr_service_ready_for_redownload("radarr"):
                self._set_fix_status_by_key(file_key, "Error: Radarr not configured")
                self._active_redownload_fix_key = None
                self._start_next_redownload_fix()
                return
            self.output.append(f"Fixes: Radarr redownload requested for '{media_term}'")
            self.radarr_redownload_worker = RadarrRedownloadWorker(media_term)
            self.radarr_redownload_worker.log.connect(self.add_log)
            self.radarr_redownload_worker.finished.connect(
                lambda msg, key=file_key: self._redownload_fix_finished(key, msg)
            )
            self.radarr_redownload_worker.start()
            return

        self._set_fix_status_by_key(file_key, "Skipped")
        self._active_redownload_fix_key = None
        self._start_next_redownload_fix()

    def _redownload_fix_finished(self, file_key: str, message: str) -> None:
        self.output.append(f"Fixes: {message}")
        self._set_fix_status_by_key(file_key, "Redownload requested")
        self._active_redownload_fix_key = None
        self._start_next_redownload_fix()
        self._update_fixes_status_label()

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

        scan_root = self._current_scan_root()
        cleared_stale_resume = False
        if self.resume_after is not None and self.resume_scan_root != scan_root:
            self.resume_after = None
            self.resume_scan_root = None
            cleared_stale_resume = True

        self.start_button.setEnabled(False)
        self.new_scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        is_resume = self.resume_after is not None
        self._current_scan_is_resume = is_resume
        self._defer_fixes_refresh = True
        self._fixes_refresh_needed = False
        if not is_resume:
            self.current_scan_started_at = datetime.now(timezone.utc)
        if not is_resume:
            self._reset_current_scan_bad_files_model()
            self.output.clear()
            self.table.setRowCount(0)
            self.fixes_table.setRowCount(0)
            self._update_fixes_status_label()
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
        self.scan_root_label.setText(f"Scan root: {scan_root}")
        if cleared_stale_resume:
            self.output.append(
                "Scan root changed since the stopped scan; starting a fresh scan."
            )
        self.output.append(f"Scan root: {scan_root}")
        warning = _selected_root_subfolder_warning(scan_root)
        if warning:
            self.output.append(warning)
        if is_resume:
            self.output.append(f"Resuming after: {self.resume_after}")

        self.cache_hits = 0
        self.cache_misses = 0

        self.worker = ScanWorker(
            scan_root,
            resume_after=self.resume_after,
            max_workers=self._current_scan_max_workers(),
        )

        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.add_log)
        self.worker.issue.connect(self.add_issue)
        self.worker.finished.connect(self.scan_finished)

        self.worker.start()

    def start_fresh_scan(self):
        """Clear results and start a new scan from the beginning."""
        self.resume_after = None
        self.resume_scan_root = None
        self.output.clear()
        self.table.setRowCount(0)
        self.fixes_table.setRowCount(0)
        self._update_fixes_status_label()
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
        self.auto_fix_worker.progress.connect(self.update_auto_fix_progress)
        self.auto_fix_worker.finished.connect(self.auto_fix_finished)
        self.auto_fix_progress.setVisible(True)
        self.auto_fix_progress.setMaximum(1)
        self.auto_fix_progress.setValue(0)
        self.auto_fix_stop_button.setVisible(True)
        self.auto_fix_worker.start()

    def auto_fix_folder(self):
        """Run ffmpeg auto-fix across all media files in the selected file's folder."""
        input_path, _issues_text = self._selected_file_and_issues()
        if not input_path:
            return

        folder = os.path.dirname(input_path)
        if not folder:
            return

        from nas_checker.scan.scanner import MEDIA_EXTENSIONS

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
        self.auto_fix_worker.progress.connect(self.update_auto_fix_progress)
        self.auto_fix_worker.finished.connect(self.auto_fix_finished)
        self.auto_fix_progress.setVisible(True)
        self.auto_fix_progress.setMaximum(len(media_inputs))
        self.auto_fix_progress.setValue(0)
        self.auto_fix_stop_button.setVisible(True)
        self.auto_fix_stop_button.setEnabled(True)
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
        issue_codes = collect_issue_codes(issues_text)

        missing_audio = (
            ISSUE_NO_AUDIO in issue_codes or "no audio stream found" in issues_lower
        )
        missing_video = (
            ISSUE_NO_VIDEO in issue_codes or "no video stream found" in issues_lower
        )
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

        if not self._arr_service_ready_for_redownload("sonarr"):
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
        issue_codes = collect_issue_codes(issues_text)
        missing_audio = (
            ISSUE_NO_AUDIO in issue_codes or "no audio stream found" in issues_lower
        )
        missing_video = (
            ISSUE_NO_VIDEO in issue_codes or "no video stream found" in issues_lower
        )
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

        if not self._arr_service_ready_for_redownload("radarr"):
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
        self.auto_fix_progress.setVisible(False)
        self.auto_fix_stop_button.setVisible(False)
        self.auto_fix_stop_button.setEnabled(True)
        for file_key in self._active_auto_fix_keys:
            self._set_fix_status_by_key(file_key, "Finished - review log")
        self._active_auto_fix_keys = set()
        self._update_fixes_status_label()
        if outputs_text:
            self.output.append("Auto-fix outputs:")
            self.output.append(outputs_text)

    def stop_auto_fix(self):
        if self.auto_fix_worker and self.auto_fix_worker.isRunning():
            self.auto_fix_worker.request_stop()
            self.auto_fix_stop_button.setEnabled(False)

    def update_auto_fix_progress(self, current: int, total: int):
        self.auto_fix_progress.setMaximum(max(total, 1))
        self.auto_fix_progress.setValue(current)
        self.label.setText(f"Auto-fixing {current}/{total}")

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
            issue_codes = collect_issue_codes(issue_text)
            type_matches = (
                True
                if not selected_issue_ids
                else any(
                    self.issue_type_filter_map[issue_id](issue_codes)
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

    def update_progress(
        self, current, total, speed, remaining, cache_hits=0, cache_misses=0
    ):
        self.cache_hits = int(cache_hits or 0)
        self.cache_misses = int(cache_misses or 0)

        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.setWindowTitle(f"NAS Media Validator — Issues: {self.table.rowCount()}")

        self.label.setText(f"Scanning {current}/{total}")
        issues = self.table.rowCount()

        eta = f"{int(remaining)}s" if remaining else "--"
        cache_total = self.cache_hits + self.cache_misses
        cache_pct = (
            f"{(self.cache_hits / cache_total) * 100:.0f}%" if cache_total > 0 else "--"
        )

        self.stats.setText(
            f"Files scanned: {current} | Issues: {issues} | Speed: {speed:.1f}/s | "
            f"ETA: {eta} | Cache: {cache_pct}"
        )

    def add_log(self, message):

        self.output.append(message)

        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def scan_finished(self, payload):
        self.start_button.setEnabled(True)
        self.new_scan_button.setEnabled(True)
        self._defer_fixes_refresh = False

        bad_files = payload.get("bad_files", [])
        stats_delta = payload.get("stats", {})
        self._merge_bad_file_entries_into_current_scan(bad_files)

        self.cache_hits = int(stats_delta.get("cache_hits", 0) or 0)
        self.cache_misses = int(stats_delta.get("cache_misses", 0) or 0)

        if self.library_stats_total is None:
            self.library_stats_total = self._empty_library_stats_total()

        self._merge_library_stats_delta(stats_delta)
        self._render_library_stats()

        if payload.get("cancelled"):
            self.resume_after = payload.get("resume_after")
            self.resume_scan_root = self.media_folder
            self.label.setText("Stopped — ready to resume")
            self.output.append(
                f"Scan stopped by user. Resume from: {self.resume_after}"
            )
            issue_snapshot = self._current_scan_bad_files_snapshot()
            self.output.append(f"Files with issues so far: {len(issue_snapshot)}")
            if self._fixes_refresh_needed:
                self.refresh_fixes_from_issues(preserve_state=True)
                self._fixes_refresh_needed = False
            return

        self.resume_after = None
        self.resume_scan_root = None
        self.label.setText("Scan Complete")

        if self._current_scan_is_resume:
            history_bad_files = self._current_scan_bad_files_snapshot()
        else:
            history_bad_files = self._normalized_bad_file_entries(bad_files)
            if not history_bad_files:
                history_bad_files = self._current_scan_bad_files_snapshot()

        issue_count = self._bad_files_issue_count(history_bad_files)
        self.output.append(
            f"Scan complete. Files with issues: {len(history_bad_files)}; "
            f"total issues: {issue_count}."
        )
        self.output.append(
            "Issue details are available in the Issues table, exports, and scan history."
        )

        self._persist_completed_scan_to_history(history_bad_files)
        self._render_nas_health_tab_latest()
        self._check_overdue_scan_prompt()
        if self._fixes_refresh_needed:
            QTimer.singleShot(0, self._refresh_fixes_and_handle_auto_fix_after_scan)
            self._fixes_refresh_needed = False
        else:
            QTimer.singleShot(0, self._handle_auto_fix_after_scan)

    def _refresh_fixes_and_handle_auto_fix_after_scan(self) -> None:
        self.refresh_fixes_from_issues(True)
        self._handle_auto_fix_after_scan()

    def _handle_auto_fix_after_scan(self) -> None:
        mode = self._current_auto_fix_mode()
        if mode == AUTO_FIX_MODE_OFF:
            return

        if self.auto_fix_worker and self.auto_fix_worker.isRunning():
            self.output.append("Auto Fix after scan skipped: auto-fix already running.")
            return

        entries = self._safe_auto_fix_entries_from_table()
        count = len(entries)
        if count <= 0:
            self.output.append("Auto Fix after scan: no safe ffmpeg fixes found.")
            return

        if mode == AUTO_FIX_MODE_PROMPT:
            response = QMessageBox.question(
                self,
                "Run safe auto fixes?",
                (
                    f"{count} fixable files found. Run safe fixes now?\n\n"
                    "Only ffmpeg-supported safe fixes will run. Backups are created "
                    "before replace. Redownload and manual-review items are excluded."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if response != QMessageBox.Yes:
                self.output.append("Auto Fix after scan: user skipped safe fixes.")
                return
            self.output.append("Auto Fix after scan: user confirmed safe fixes.")
            self._start_ffmpeg_auto_fix_entries(entries, "Auto Fix after scan")
            return

        if mode == AUTO_FIX_MODE_AUTO_RUN:
            self.output.append(
                "Auto Fix after scan: starting safe ffmpeg fixes automatically."
            )
            self._start_ffmpeg_auto_fix_entries(entries, "Auto Fix after scan")

    def _browse_media_folder(self) -> None:
        start_dir = self.scan_media_folder_edit.text() or self.media_folder
        folder = QFileDialog.getExistingDirectory(
            self, "Select media library folder", start_dir
        )
        if folder:
            self.scan_media_folder_edit.setText(normalize_scan_path(folder))
            self._update_worker_recommendation_label()

    def _table_bad_files_for_export(self) -> list[tuple[str, list]]:
        rows: list[tuple[str, list]] = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            file_item = self.table.item(row, 0)
            issue_item = self.table.item(row, 1)
            if file_item is None or issue_item is None:
                continue
            file_path = file_item.text()
            issues = [
                part.strip()
                for part in (issue_item.text() or "").split(",")
                if part.strip()
            ]
            rows.append((file_path, normalize_issues(issues)))
        return rows

    def export_issues_csv(self) -> None:
        rows = self._table_bad_files_for_export()
        if not rows:
            self.output.append("Export CSV: no visible issues to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export issues CSV", "issues_export.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        save_report(rows, filename=path)
        self.output.append(f"Exported CSV: {path}")

    def export_issues_json(self) -> None:
        rows = self._table_bad_files_for_export()
        if not rows:
            self.output.append("Export JSON: no visible issues to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export issues JSON", "issues_export.json", "JSON Files (*.json)"
        )
        if not path:
            return
        save_report_json(rows, filename=path)
        self.output.append(f"Exported JSON: {path}")

    def load_scan_from_history(self, row: int, _column: int) -> None:
        if row < 0:
            return

        scan_id_item = self.history_table.item(row, 0)
        if scan_id_item is None:
            return

        scan_id = scan_id_item.data(Qt.UserRole)
        if not scan_id:
            return

        record = self.scan_history.get_scan(scan_id)
        if not record:
            return

        self._show_history_record(record)

    def _render_scan_history_table(self) -> None:
        scans = self.scan_history.scans()

        self.history_table.setRowCount(0)
        for i, record in enumerate(scans):
            self.history_table.insertRow(i)

            stats = record.get("stats") or {}
            scanned_files = stats.get("scanned_files", "")
            files_with_issues = stats.get("files_with_issues", "")
            issues_total = record.get("issues_total", "")

            started_at = record.get("started_at", "")
            completed_at = record.get("completed_at", "")
            cancelled = bool(record.get("cancelled"))
            status = "Cancelled" if cancelled else "Complete"

            started_item = QTableWidgetItem(str(started_at))
            started_item.setData(Qt.UserRole, record.get("id"))
            started_item.setToolTip(f"Completed: {completed_at}")

            status_item = QTableWidgetItem(status)
            scanned_item = QTableWidgetItem(str(scanned_files))
            issues_with_item = QTableWidgetItem(str(files_with_issues))
            issues_total_item = QTableWidgetItem(str(issues_total))

            self.history_table.setItem(i, 0, started_item)
            self.history_table.setItem(i, 1, status_item)
            self.history_table.setItem(i, 2, scanned_item)
            self.history_table.setItem(i, 3, issues_with_item)
            self.history_table.setItem(i, 4, issues_total_item)

    def _show_history_record(self, record: dict) -> None:
        stats = record.get("stats") or {}
        bad_files = record.get("bad_files") or []
        bad_file_entries = self._normalized_bad_file_entries(bad_files)

        self.output.clear()
        self.table.setRowCount(0)
        self.fixes_table.setRowCount(0)
        self._update_fixes_status_label()

        # Load stats.
        self.library_stats_total = self._empty_library_stats_total()
        self._merge_library_stats_delta(stats)
        self._render_library_stats()

        started_at = record.get("started_at", "")
        completed_at = record.get("completed_at", "")
        cancelled = bool(record.get("cancelled"))
        status = "Cancelled" if cancelled else "Complete"

        self.output.append(
            f"Loaded scan history: {status}\nStarted: {started_at}\nCompleted: {completed_at}"
        )
        self.output.append(
            f"Files with issues: {len(bad_file_entries)}; "
            f"total issues: {self._bad_files_issue_count(bad_file_entries)}."
        )
        self.output.append("Issue details are loaded in the Issues table.")

        self._load_bad_file_entries_into_issue_table(bad_file_entries)

        self._render_nas_health_for_record(record)
        self.refresh_fixes_from_issues(preserve_state=False)
        self.label.setText("Viewing Scan History")

    def _load_bad_file_entries_into_issue_table(
        self, bad_file_entries: list[dict]
    ) -> None:
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(bad_file_entries))
            for row, entry in enumerate(bad_file_entries):
                file_path = entry.get("file")
                issues = normalize_issues(entry.get("issues") or [])
                file_item = QTableWidgetItem(str(file_path))
                file_item.setData(Qt.UserRole, self.canonicalize_path(file_path))
                issue_item = QTableWidgetItem(
                    ", ".join(issue_message(issue) for issue in issues)
                )

                self.table.setItem(row, 0, file_item)
                self.table.setItem(row, 1, issue_item)
                file_item.setBackground(Qt.darkRed)
                issue_item.setBackground(Qt.darkRed)
        finally:
            self.table.setUpdatesEnabled(True)

        self.apply_issue_filter(self.issue_filter.text())

    def _get_table_bad_files_snapshot(self) -> list[dict]:
        snapshot: list[dict] = []
        for row in range(self.table.rowCount()):
            file_item = self.table.item(row, 0)
            issue_item = self.table.item(row, 1)
            if file_item is None or issue_item is None:
                continue

            file_path = file_item.text()
            issue_text = issue_item.text() or ""

            # `add_issue()` concatenates unique issues with ", ".
            issues = [s.strip() for s in issue_text.split(",") if s.strip()]
            snapshot.append({"file": file_path, "issues": normalize_issues(issues)})

        return snapshot

    def _persist_completed_scan_to_history(
        self, bad_files_snapshot: list[dict] | None = None
    ) -> None:
        # Only persist after a real completion (not when stopped for resume).
        if not self.library_stats_total:
            return

        if not self.current_scan_started_at:
            self.current_scan_started_at = datetime.now(timezone.utc)

        # Build a deep-enough copy so future UI actions don't mutate history objects.
        stats_copy = json.loads(json.dumps(self.library_stats_total))
        if bad_files_snapshot is None:
            bad_files_snapshot = self._current_scan_bad_files_snapshot()
        if not bad_files_snapshot and self.table.rowCount() > 0:
            bad_files_snapshot = self._get_table_bad_files_snapshot()
        bad_files_snapshot = json.loads(json.dumps(bad_files_snapshot))

        issues_total = 0
        for entry in bad_files_snapshot:
            issues_total += len(entry.get("issues") or [])

        record = {
            "started_at": self.current_scan_started_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "completed_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "cancelled": False,
            "stats": stats_copy,
            "bad_files": bad_files_snapshot,
            "issues_total": issues_total,
        }

        self.scan_history.add_scan(record)
        self._render_scan_history_table()
        self.current_scan_started_at = None

    def _init_health_settings_and_render(self) -> None:
        self.health_settings_path = os.path.join(
            os.path.dirname(__file__), "health_settings.json"
        )
        self.health_settings = self._load_health_settings()
        self._active_health_record: dict | None = None
        self._active_health_anchor_date: datetime | None = None

        # Prevent signal handlers from saving while we apply defaults.
        self._suppress_health_schedule_save = True
        try:
            self._apply_health_settings_to_ui()
        finally:
            self._suppress_health_schedule_save = False

        self._render_nas_health_tab_latest()
        self._render_drive_info_in_nas_health_tab()
        self._check_overdue_scan_prompt()

    def _init_scan_rules_settings_and_render(self) -> None:
        self.scan_rules_settings_path = os.path.join(
            os.path.dirname(__file__), "scan_rules_settings.json"
        )
        self.scan_path_settings_path = get_default_scan_path_settings_path()
        self.scan_path_settings = load_scan_path_settings(self.scan_path_settings_path)
        self.scan_rules_settings = load_scan_rules_settings(
            self.scan_rules_settings_path
        )

        self.scan_media_folder_edit.setText(self.media_folder)
        self.scan_workers_auto_checkbox.setChecked(
            bool(self.scan_path_settings.get("auto_workers", DEFAULT_AUTO_WORKERS))
        )
        self.scan_workers_manual_spin.setValue(
            int(self.scan_path_settings.get("manual_workers", DEFAULT_MANUAL_WORKERS))
        )
        self._set_auto_fix_mode_combo(
            self.scan_path_settings.get("auto_fix_mode", DEFAULT_AUTO_FIX_MODE)
        )
        self._on_auto_workers_toggled(self.scan_workers_auto_checkbox.isChecked())
        self._update_read_speed_status_label()

        self.scan_rules_containers_edit.setText(
            ",".join(self.scan_rules_settings.get("containers") or [])
        )
        self.scan_rules_video_codecs_edit.setText(
            ",".join(self.scan_rules_settings.get("video_codecs") or [])
        )
        self.scan_rules_audio_codecs_edit.setText(
            ",".join(self.scan_rules_settings.get("audio_codecs") or [])
        )
        self.scan_rules_min_size_spin.setValue(
            int(self.scan_rules_settings.get("min_file_size_bytes", 1_000_000))
        )
        self.scan_rules_check_subtitles.setChecked(
            bool(self.scan_rules_settings.get("check_subtitles", False))
        )
        self.scan_rules_check_hdr.setChecked(
            bool(self.scan_rules_settings.get("check_hdr", False))
        )
        self.scan_rules_check_tenbit_h264.setChecked(
            bool(self.scan_rules_settings.get("check_tenbit_h264", True))
        )
        self.scan_rules_check_multiple_audio.setChecked(
            bool(self.scan_rules_settings.get("check_multiple_audio", False))
        )
        self.scan_rules_check_multiple_subtitle.setChecked(
            bool(self.scan_rules_settings.get("check_multiple_subtitle", False))
        )
        self.scan_rules_check_multiple_commentary.setChecked(
            bool(self.scan_rules_settings.get("check_multiple_commentary", True))
        )
        self.scan_rules_check_wrong_resolution.setChecked(
            bool(self.scan_rules_settings.get("check_wrong_resolution", True))
        )

        self.scan_rules_settings_status_label.setText("Scan settings loaded.")

    def _init_arr_settings_and_render(self) -> None:
        self.arr_config_path = get_default_arr_config_path()
        self.arr_settings = load_arr_config(self.arr_config_path) or {}
        self._apply_arr_settings_to_ui()
        self.arr_settings_status_label.setText(
            f"Arr settings loaded from {self.arr_config_path}."
        )

    def _apply_arr_settings_to_ui(self) -> None:
        for service in ("sonarr", "radarr"):
            service_config = (self.arr_settings or {}).get(service) or {}
            enabled_checkbox = getattr(self, f"{service}_enabled_checkbox")
            base_url_edit = getattr(self, f"{service}_base_url_edit")
            api_key_edit = getattr(self, f"{service}_api_key_edit")

            enabled_checkbox.setChecked(bool(service_config.get("enabled", False)))
            base_url_edit.setText(str(service_config.get("base_url") or ""))
            api_key_edit.setText(str(service_config.get("api_key") or ""))

    def _collect_arr_settings_from_ui(self) -> dict:
        return {
            "sonarr": {
                "enabled": self.sonarr_enabled_checkbox.isChecked(),
                "base_url": self.sonarr_base_url_edit.text().strip(),
                "api_key": self.sonarr_api_key_edit.text().strip(),
            },
            "radarr": {
                "enabled": self.radarr_enabled_checkbox.isChecked(),
                "base_url": self.radarr_base_url_edit.text().strip(),
                "api_key": self.radarr_api_key_edit.text().strip(),
            },
        }

    def _arr_settings_validation_errors(self, config: dict) -> list[str]:
        errors = []
        for service in ("sonarr", "radarr"):
            service_config = (config or {}).get(service) or {}
            if service_config.get("enabled"):
                errors.extend(validate_arr_service_config(service, service_config))
        return errors

    def _save_arr_settings_from_ui(self) -> bool:
        config = self._collect_arr_settings_from_ui()
        errors = self._arr_settings_validation_errors(config)
        if errors:
            self.arr_settings_status_label.setText(" ".join(errors))
            return False

        saved_path = save_arr_config(config, self.arr_config_path)
        self.arr_settings = load_arr_config(saved_path) or {}
        self._apply_arr_settings_to_ui()
        self.arr_settings_status_label.setText(f"Arr settings saved to {saved_path}.")
        return True

    def _test_arr_connection(self, service: str) -> None:
        config = self._collect_arr_settings_from_ui()
        service_config = (config or {}).get(service) or {}
        errors = validate_arr_service_config(
            service,
            {**service_config, "enabled": True},
        )
        if errors:
            self.arr_settings_status_label.setText(" ".join(errors))
            return

        worker = self.arr_connection_test_workers.get(service)
        if worker and worker.isRunning():
            self.arr_settings_status_label.setText(
                f"{service.capitalize()} connection test already running..."
            )
            return

        test_button = getattr(self, f"{service}_test_button")
        test_button.setEnabled(False)
        self.arr_settings_status_label.setText(
            f"Testing {service.capitalize()} connection..."
        )
        worker = ArrConnectionTestWorker(
            service,
            service_config.get("base_url", ""),
            service_config.get("api_key", ""),
        )
        self.arr_connection_test_workers[service] = worker
        worker.finished.connect(
            lambda message, ok, svc=service: self._arr_connection_test_finished(
                svc,
                message,
                ok,
            )
        )
        worker.start()

    def _arr_connection_test_finished(
        self,
        service: str,
        message: str,
        ok: bool,
    ) -> None:
        getattr(self, f"{service}_test_button").setEnabled(True)
        self.arr_settings_status_label.setText(message)
        self.output.append(message)
        self.arr_connection_test_workers.pop(service, None)

    def _arr_service_ready_for_redownload(self, service: str) -> bool:
        config = load_arr_config() or {}
        service_config = (config or {}).get(service) or {}
        errors = validate_arr_service_config(service, service_config)
        if errors:
            for error in errors:
                self.output.append(error)
            if hasattr(self, "arr_settings_status_label"):
                self.arr_settings_status_label.setText(" ".join(errors))
            return False
        return True

    def _current_scan_max_workers(self) -> int | None:
        if self.scan_workers_auto_checkbox.isChecked():
            return None
        return int(self.scan_workers_manual_spin.value())

    def _current_scan_root(self) -> str:
        media_folder = normalize_scan_path(self.scan_media_folder_edit.text())
        self.media_folder = media_folder
        self.scan_media_folder_edit.setText(media_folder)
        self.scan_root_label.setText(f"Scan root: {media_folder}")
        if hasattr(self, "scan_path_settings_path"):
            save_scan_path_settings(
                {
                    "media_folder": media_folder,
                    "auto_workers": self.scan_workers_auto_checkbox.isChecked(),
                    "manual_workers": self.scan_workers_manual_spin.value(),
                    "auto_fix_mode": self._current_auto_fix_mode(),
                },
                self.scan_path_settings_path,
            )
            self.scan_path_settings = load_scan_path_settings(
                self.scan_path_settings_path
            )
        return media_folder

    def _on_auto_workers_toggled(self, enabled: bool) -> None:
        self.scan_workers_manual_spin.setEnabled(not enabled)
        self._update_worker_recommendation_label()

    def _update_worker_recommendation_label(self) -> None:
        if not hasattr(self, "scan_workers_recommendation_label"):
            return

        media_folder = normalize_scan_path(self.scan_media_folder_edit.text())
        try:
            measured = None
            scan_path_settings = getattr(self, "scan_path_settings", {})
            settings_media_folder = normalize_scan_path(
                scan_path_settings.get("media_folder")
            )
            if settings_media_folder == media_folder:
                measured = scan_path_settings.get(
                    EFFECTIVE_READ_MB_S_KEY
                ) or scan_path_settings.get(MEASURED_READ_MB_S_KEY)
            details = get_scan_worker_recommendation(media_folder, measured)
            workers = int(details.get("workers") or DEFAULT_MANUAL_WORKERS)
            cpu_count = int(details.get("cpu_count") or 0)
            storage_class = details.get("storage_class") or "unknown"
            estimated = int(details.get("estimated_read_mb_s") or 0)
            effective_read = details.get("effective_measured_read_mb_s") or details.get(
                "measured_read_mb_s"
            )
            raw_read = scan_path_settings.get(RAW_MEASURED_READ_MB_S_KEY)
            settings_confidence = scan_path_settings.get(MEASURED_READ_CONFIDENCE_KEY)
            if effective_read:
                estimate_text = f", effective {float(effective_read):.0f} MB/s"
                if settings_confidence == "low" and raw_read:
                    estimate_text += ", cached result ignored"
            else:
                estimate_text = f", est {estimated} MB/s" if estimated else ""
            recommendation = (
                f"{workers} workers (CPU {cpu_count}, storage {storage_class}"
                f"{estimate_text})"
            )
            if self.scan_workers_auto_checkbox.isChecked():
                text = f"Auto: {recommendation}"
            else:
                text = (
                    f"Manual: {self.scan_workers_manual_spin.value()} workers. "
                    f"Recommended: {recommendation}"
                )
        except Exception:
            text = "Auto: recommendation unavailable"

        self.scan_workers_recommendation_label.setText(text)

    def _update_read_speed_status_label(self) -> None:
        if not hasattr(self, "read_speed_status_label"):
            return
        scan_path_settings = getattr(self, "scan_path_settings", {})
        measured = scan_path_settings.get(
            EFFECTIVE_READ_MB_S_KEY
        ) or scan_path_settings.get(MEASURED_READ_MB_S_KEY)
        measured_at = scan_path_settings.get(MEASURED_READ_AT_KEY)
        if measured:
            suffix = f" at {measured_at}" if measured_at else ""
            confidence = scan_path_settings.get(MEASURED_READ_CONFIDENCE_KEY)
            raw_read = scan_path_settings.get(RAW_MEASURED_READ_MB_S_KEY)
            confidence_text = (
                "; cached/implausible result ignored; "
                f"keeping previous effective speed {float(measured):.0f} MB/s"
                if confidence == "low" and raw_read
                else ""
            )
            self.read_speed_status_label.setText(
                f"Effective read speed: {float(measured):.0f} MB/s"
                f"{suffix}{confidence_text}"
            )
        else:
            self.read_speed_status_label.setText("Read speed: not tested")

    def _start_read_speed_test(self) -> None:
        if (
            self.read_speed_benchmark_worker
            and self.read_speed_benchmark_worker.isRunning()
        ):
            self.read_speed_status_label.setText("Read speed test already running...")
            self.worker_controls_group.setFocus(Qt.OtherFocusReason)
            return

        media_folder = normalize_scan_path(self.scan_media_folder_edit.text())
        self.read_speed_test_button.setEnabled(False)
        self.read_speed_status_label.setText("Read speed test running...")
        self.worker_controls_group.setFocus(Qt.OtherFocusReason)
        self.read_speed_benchmark_worker = ReadSpeedBenchmarkWorker(media_folder)
        self.read_speed_benchmark_worker.progress.connect(
            self.read_speed_status_label.setText
        )
        self.read_speed_benchmark_worker.finished.connect(
            self._read_speed_test_finished
        )
        self.read_speed_benchmark_worker.start()

    def _read_speed_test_finished(self, result: dict) -> None:
        self.read_speed_test_button.setEnabled(True)
        mb_s = float((result or {}).get("mb_s") or 0.0)
        files_sampled = int((result or {}).get("files_sampled") or 0)
        bytes_read = int((result or {}).get("bytes_read") or 0)
        sampled_mb = bytes_read / (1024 * 1024)
        confidence = (result or {}).get("confidence") or "normal"
        warning = (result or {}).get("warning") or ""
        error = (result or {}).get("error")
        message = (result or {}).get("message") or ""

        if error or mb_s <= 0:
            detail = f": {message}" if message else ""
            self.read_speed_status_label.setText(f"Read speed test failed{detail}")
            self.read_speed_benchmark_worker = None
            return

        measured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        media_folder = normalize_scan_path(self.scan_media_folder_edit.text())
        previous_effective = None
        if (
            normalize_scan_path(self.scan_path_settings.get("media_folder"))
            == media_folder
        ):
            previous_effective = self.scan_path_settings.get(
                EFFECTIVE_READ_MB_S_KEY
            ) or self.scan_path_settings.get(MEASURED_READ_MB_S_KEY)
        evaluation = evaluate_read_benchmark_result(
            media_folder,
            mb_s,
            previous_effective,
            confidence,
        )
        recommendation_details = evaluation["recommendation_details"]
        low_confidence = evaluation["confidence"] == "low"
        effective_mb_s = evaluation["effective_mb_s"]
        save_scan_path_settings(
            {
                "media_folder": media_folder,
                MEASURED_READ_MB_S_KEY: effective_mb_s,
                EFFECTIVE_READ_MB_S_KEY: effective_mb_s,
                RAW_MEASURED_READ_MB_S_KEY: mb_s,
                MEASURED_READ_CONFIDENCE_KEY: "low" if low_confidence else "normal",
                MEASURED_READ_AT_KEY: measured_at,
            },
            self.scan_path_settings_path,
        )
        self.scan_path_settings = load_scan_path_settings(self.scan_path_settings_path)
        self.media_folder = media_folder
        self.scan_media_folder_edit.setText(self.media_folder)
        warnings = [
            text
            for text in (
                warning,
                recommendation_details.get("read_speed_warning") or "",
            )
            if text
        ]
        warning_text = " ".join(warnings)
        sampled_text = f"sampled {sampled_mb:.1f} MB from {files_sampled} file(s)"
        if low_confidence:
            if effective_mb_s:
                prefix = f"Effective read speed: {float(effective_mb_s):.0f} MB/s"
            else:
                prefix = "Read speed unchanged"
            reason = (
                evaluation["ignore_reason"]
                or warning_text
                or "cached/low-confidence result ignored"
            )
            status = (
                f"{prefix}; {sampled_text}; raw {mb_s:.1f} MB/s discarded. " f"{reason}"
            )
        else:
            status = f"Effective read speed: {mb_s:.1f} MB/s; {sampled_text}."
        self.read_speed_status_label.setText(status)
        self._update_worker_recommendation_label()
        self.read_speed_benchmark_worker = None

    def _parse_csv_list(self, text: str) -> list[str]:
        # Parse comma-separated tokens; normalize to lowercase; strip dots.
        items: list[str] = []
        for raw in (text or "").split(","):
            s = raw.strip().lower()
            if not s:
                continue
            if s.startswith("."):
                s = s[1:]
            items.append(s)
        # stable unique
        seen: set[str] = set()
        out: list[str] = []
        for x in items:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def _save_scan_rules_settings_from_ui(self) -> None:
        containers = self._parse_csv_list(self.scan_rules_containers_edit.text())
        video_codecs = self._parse_csv_list(self.scan_rules_video_codecs_edit.text())
        audio_codecs = self._parse_csv_list(self.scan_rules_audio_codecs_edit.text())
        media_folder = normalize_scan_path(self.scan_media_folder_edit.text())

        # If user clears a field, fall back to defaults for that category.
        settings = dict(DEFAULT_SCAN_RULES_SETTINGS)
        if containers:
            settings["containers"] = containers
        if video_codecs:
            settings["video_codecs"] = video_codecs
        if audio_codecs:
            settings["audio_codecs"] = audio_codecs

        settings["min_file_size_bytes"] = int(self.scan_rules_min_size_spin.value())
        settings["check_subtitles"] = self.scan_rules_check_subtitles.isChecked()
        settings["check_hdr"] = self.scan_rules_check_hdr.isChecked()
        settings["check_tenbit_h264"] = self.scan_rules_check_tenbit_h264.isChecked()
        settings["check_multiple_audio"] = (
            self.scan_rules_check_multiple_audio.isChecked()
        )
        settings["check_multiple_subtitle"] = (
            self.scan_rules_check_multiple_subtitle.isChecked()
        )
        settings["check_multiple_commentary"] = (
            self.scan_rules_check_multiple_commentary.isChecked()
        )
        settings["check_wrong_resolution"] = (
            self.scan_rules_check_wrong_resolution.isChecked()
        )

        save_scan_rules_settings(settings, self.scan_rules_settings_path)
        save_scan_path_settings(
            {
                "media_folder": media_folder,
                "auto_workers": self.scan_workers_auto_checkbox.isChecked(),
                "manual_workers": int(self.scan_workers_manual_spin.value()),
            },
            self.scan_path_settings_path,
        )
        self.scan_rules_settings = load_scan_rules_settings(
            self.scan_rules_settings_path
        )
        self.scan_path_settings = load_scan_path_settings(self.scan_path_settings_path)
        self.media_folder = media_folder
        self.scan_media_folder_edit.setText(self.media_folder)
        self._render_drive_info_in_nas_health_tab()
        self._update_worker_recommendation_label()
        self.scan_rules_settings_status_label.setText("Scan settings saved.")

    def _reset_scan_rules_settings_to_defaults(self) -> None:
        self.scan_media_folder_edit.setText(DEFAULT_MEDIA_FOLDER)
        self.scan_workers_auto_checkbox.setChecked(DEFAULT_AUTO_WORKERS)
        self.scan_workers_manual_spin.setValue(DEFAULT_MANUAL_WORKERS)
        self._on_auto_workers_toggled(self.scan_workers_auto_checkbox.isChecked())
        self.scan_rules_containers_edit.setText(
            ",".join(DEFAULT_SCAN_RULES_SETTINGS.get("containers") or [])
        )
        self.scan_rules_video_codecs_edit.setText(
            ",".join(DEFAULT_SCAN_RULES_SETTINGS.get("video_codecs") or [])
        )
        self.scan_rules_audio_codecs_edit.setText(
            ",".join(DEFAULT_SCAN_RULES_SETTINGS.get("audio_codecs") or [])
        )
        self.scan_rules_min_size_spin.setValue(
            int(DEFAULT_SCAN_RULES_SETTINGS.get("min_file_size_bytes", 1_000_000))
        )
        self.scan_rules_check_subtitles.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_subtitles", False))
        )
        self.scan_rules_check_hdr.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_hdr", False))
        )
        self.scan_rules_check_tenbit_h264.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_tenbit_h264", True))
        )
        self.scan_rules_check_multiple_audio.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_multiple_audio", False))
        )
        self.scan_rules_check_multiple_subtitle.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_multiple_subtitle", False))
        )
        self.scan_rules_check_multiple_commentary.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_multiple_commentary", True))
        )
        self.scan_rules_check_wrong_resolution.setChecked(
            bool(DEFAULT_SCAN_RULES_SETTINGS.get("check_wrong_resolution", True))
        )
        self.scan_rules_settings_status_label.setText("Defaults loaded (click Save).")

    def _load_health_settings(self) -> dict:
        defaults = {
            "schedule_type": "Weekly",
            "weekday": 6,  # Sunday
            "custom_date": datetime.now(timezone.utc).date().isoformat(),
            "auto_start_when_overdue": False,
        }

        try:
            if os.path.exists(self.health_settings_path):
                with open(self.health_settings_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        defaults.update(loaded)
        except Exception:
            # Ignore invalid/corrupt settings.
            pass

        # Validate/clamp.
        st = defaults.get("schedule_type") or "Weekly"
        if st not in ("Daily", "Weekly", "Custom date"):
            st = "Weekly"
        defaults["schedule_type"] = st

        try:
            weekday = int(defaults.get("weekday", 6))
        except Exception:
            weekday = 6
        weekday = max(0, min(6, weekday))
        defaults["weekday"] = weekday

        cd = defaults.get("custom_date")
        if not isinstance(cd, str) or not cd:
            cd = datetime.now(timezone.utc).date().isoformat()
        defaults["custom_date"] = cd
        defaults["auto_start_when_overdue"] = bool(
            defaults.get("auto_start_when_overdue", False)
        )

        return defaults

    def _save_health_settings(self) -> None:
        try:
            with open(self.health_settings_path, "w", encoding="utf-8") as f:
                json.dump(self.health_settings, f, indent=2)
        except Exception:
            pass

    def _apply_health_settings_to_ui(self) -> None:
        schedule_type = self.health_settings.get("schedule_type", "Weekly")

        idx = self.health_schedule_type_combo.findText(schedule_type)
        if idx >= 0:
            self.health_schedule_type_combo.setCurrentIndex(idx)

        weekday_idx = int(self.health_settings.get("weekday", 6))
        weekday_name = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ][weekday_idx]

        weekday_ui_idx = self.health_weekday_combo.findText(weekday_name)
        if weekday_ui_idx >= 0:
            self.health_weekday_combo.setCurrentIndex(weekday_ui_idx)

        cd = self.health_settings.get("custom_date")
        if isinstance(cd, str):
            qd = QDate.fromString(cd, "yyyy-MM-dd")
            if qd.isValid():
                self.health_custom_date_edit.setDate(qd)

        self.health_weekday_combo.setVisible(schedule_type == "Weekly")
        self.health_custom_date_edit.setVisible(schedule_type == "Custom date")
        self.health_auto_start_checkbox.setChecked(
            bool(self.health_settings.get("auto_start_when_overdue", False))
        )

    def _weekday_name_to_index(self, weekday_name: str) -> int:
        names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        try:
            return names.index(weekday_name)
        except ValueError:
            return 6

    def _on_health_schedule_changed(self) -> None:
        if getattr(self, "_suppress_health_schedule_save", False):
            return

        schedule_type = self.health_schedule_type_combo.currentText()
        self.health_settings["schedule_type"] = schedule_type

        if schedule_type == "Weekly":
            self.health_settings["weekday"] = self._weekday_name_to_index(
                self.health_weekday_combo.currentText()
            )

        if schedule_type == "Custom date":
            self.health_settings["custom_date"] = (
                self.health_custom_date_edit.date().toString("yyyy-MM-dd")
            )

        self.health_weekday_combo.setVisible(schedule_type == "Weekly")
        self.health_custom_date_edit.setVisible(schedule_type == "Custom date")

        self._save_health_settings()
        self._recalculate_next_scan_label()
        self._check_overdue_scan_prompt()

    def _on_health_auto_start_changed(self) -> None:
        if getattr(self, "_suppress_health_schedule_save", False):
            return
        self.health_settings["auto_start_when_overdue"] = (
            self.health_auto_start_checkbox.isChecked()
        )
        self._save_health_settings()

    def _compute_next_scan_date(self) -> date | None:
        if not getattr(self, "_active_health_anchor_date", None):
            return None

        schedule_type = self.health_schedule_type_combo.currentText()
        anchor_date = self._active_health_anchor_date.date()

        if schedule_type == "Daily":
            return anchor_date + timedelta(days=1)
        if schedule_type == "Weekly":
            target_weekday = self._weekday_name_to_index(
                self.health_weekday_combo.currentText()
            )
            offset = (target_weekday - anchor_date.weekday()) % 7
            if offset == 0:
                offset = 7
            return anchor_date + timedelta(days=offset)

        cd = self.health_custom_date_edit.date().toString("yyyy-MM-dd")
        qd = QDate.fromString(cd, "yyyy-MM-dd")
        return (
            datetime(qd.year(), qd.month(), qd.day()).date()
            if qd.isValid()
            else anchor_date
        )

    def _check_overdue_scan_prompt(self) -> None:
        next_date = self._compute_next_scan_date()
        if next_date is None:
            self.health_overdue_label.setText("")
            return

        today_utc = datetime.now(timezone.utc).date()
        if today_utc < next_date:
            self.health_overdue_label.setText("")
            return

        days_overdue = (today_utc - next_date).days
        if days_overdue == 0:
            overdue_text = "Scan is due today."
        else:
            overdue_text = f"Scan is overdue by {days_overdue} day(s)."
        self.health_overdue_label.setText(overdue_text)

        if self._overdue_prompt_shown:
            return
        if self.worker is not None and self.worker.isRunning():
            return

        self._overdue_prompt_shown = True
        if self.health_settings.get("auto_start_when_overdue"):
            self.output.append(f"{overdue_text} Auto-starting scan.")
            self.start_fresh_scan()
            return

        reply = QMessageBox.question(
            self,
            "Scan overdue",
            f"{overdue_text}\n\nStart a scan now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self.start_fresh_scan()

    def _copy_task_scheduler_command(self) -> None:
        python_exe = sys.executable.replace('"', '\\"')
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        main_script = os.path.join(repo_root, "main.py")
        media_path = normalize_scan_path(self.scan_media_folder_edit.text()).replace(
            '"', '\\"'
        )

        schedule_type = self.health_schedule_type_combo.currentText()
        if schedule_type == "Daily":
            schedule_args = "/sc DAILY"
        elif schedule_type == "Weekly":
            weekday = self.health_weekday_combo.currentText()[:3].upper()
            schedule_args = f"/sc WEEKLY /d {weekday}"
        else:
            qd = self.health_custom_date_edit.date()
            schedule_args = f"/sc ONCE /sd {qd.month():02d}/{qd.day():02d}/{qd.year()}"

        command = (
            f'schtasks /Create /TN "NAS Media Validator Scan" /TR '
            f'"\\"{python_exe}\\" \\"{main_script}\\" --path \\"{media_path}\\"" '
            f"{schedule_args} /st 02:00 /F"
        )
        QApplication.clipboard().setText(command)
        self.output.append("Task Scheduler command copied to clipboard:")
        self.output.append(command)

    def _parse_history_iso_datetime_utc(self, s: str | None) -> datetime | None:
        if not s or not isinstance(s, str):
            return None
        try:
            # We store timestamps as "...Z" for UTC.
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def _get_latest_history_record(self) -> dict | None:
        scans = self.scan_history.scans()
        return scans[0] if scans else None

    def _render_nas_health_tab_latest(self) -> None:
        record = self._get_latest_history_record()
        if record:
            self._render_nas_health_for_record(record)
        else:
            self._active_health_record = None
            self._active_health_anchor_date = None
            self.health_ok_progress.setValue(0)
            self.health_ok_label.setText("OK%: --")
            self.health_corrupted_label.setText("Corrupted Files: --")
            self.health_unreadable_label.setText("Unreadable: --")
            self.health_unrepairable_label.setText("Unrepairable: --")
            self.health_last_scan_label.setText("Last Scan: --")
            self.health_next_scan_label.setText("Next Scan: --")

    def _render_drive_info_in_nas_health_tab(self) -> None:
        try:
            profile = get_storage_profile(self.media_folder)
            drive_type = profile.get("drive_type") or "unknown"
            drive_letter = profile.get("drive_letter") or "-"
            storage_class = profile.get("storage_class") or "unknown"
            estimated = profile.get("estimated_read_mb_s")
            disk_model = profile.get("disk_model") or ""

            self.health_drive_label.setText(f"Drive: {drive_letter}: ({drive_type})")
            self.health_storage_label.setText(f"Storage: {storage_class}")
            if estimated:
                # Match common vendor-spec units:
                # - NVMe is often advertised in GB/s
                # - SATA SSD/HDD are often advertised in MB/s
                if storage_class == "nvme":
                    estimated_gb_s = float(estimated) / 1024.0
                    self.health_read_speed_label.setText(
                        f"Estimated read speed: {estimated_gb_s:.2f} GB/s"
                    )
                else:
                    self.health_read_speed_label.setText(
                        f"Estimated read speed: {int(estimated)} MB/s"
                    )
            else:
                self.health_read_speed_label.setText("Estimated read speed: -- MB/s")

            if disk_model.strip():
                self.health_disk_model_label.setText(
                    f"Disk model: {disk_model.strip()}"
                )
            else:
                self.health_disk_model_label.setText("Disk model: --")
        except Exception:
            self.health_drive_label.setText("Drive: --")
            self.health_storage_label.setText("Storage: --")
            self.health_read_speed_label.setText("Estimated read speed: -- MB/s")
            self.health_disk_model_label.setText("Disk model: --")

    def _render_nas_health_for_record(self, record: dict) -> None:
        self._active_health_record = record

        stats = record.get("stats") or {}
        scanned_files = int(stats.get("scanned_files") or 0)
        files_with_issues = int(stats.get("files_with_issues") or 0)

        bad_files = record.get("bad_files") or []
        corrupted = 0
        unreadable = 0
        unrepairable = 0

        # Prefer category counts from the per-file issue lists so they don't overlap
        # awkwardly. This is especially important for "Unrepairable" meaning
        # "must be redownloaded".
        if isinstance(bad_files, list) and bad_files:
            for entry in bad_files:
                if not isinstance(entry, dict):
                    continue
                issues = entry.get("issues") or []
                if not isinstance(issues, list):
                    continue

                normalized = normalize_issues(issues)
                codes = {issue_code(i) for i in normalized}

                if ISSUE_FILE_SMALL in codes:
                    corrupted += 1
                if ISSUE_MEDIA_INFO_ERROR in codes:
                    unreadable += 1
                if ISSUE_NO_VIDEO in codes or ISSUE_NO_AUDIO in codes:
                    unrepairable += 1
        else:
            # Fallback to the aggregated stats counters.
            corrupted = int(stats.get("small_files") or 0)
            unreadable = int(stats.get("media_info_errors") or 0)
            unrepairable = max(files_with_issues - corrupted - unreadable, 0)

        if scanned_files > 0:
            ok_count = max(scanned_files - files_with_issues, 0)
            ok_pct = (ok_count / scanned_files) * 100.0
            self.health_ok_progress.setValue(int(round(ok_pct)))
            self.health_ok_label.setText(f"OK%: {ok_pct:.1f}% files OK")
        else:
            self.health_ok_progress.setValue(0)
            self.health_ok_label.setText("OK%: --")

        self.health_corrupted_label.setText(f"Corrupted Files: {corrupted}")
        self.health_unreadable_label.setText(f"Unreadable: {unreadable}")
        self.health_unrepairable_label.setText(f"Unrepairable: {unrepairable}")

        completed_at = record.get("completed_at")
        completed_dt = self._parse_history_iso_datetime_utc(completed_at)
        started_at = record.get("started_at")
        started_dt = self._parse_history_iso_datetime_utc(started_at)

        anchor_dt = completed_dt or started_dt
        if anchor_dt:
            self._active_health_anchor_date = anchor_dt
            self.health_last_scan_label.setText(
                f"Last Scan: {anchor_dt.date().isoformat()}"
            )
        else:
            self._active_health_anchor_date = None
            self.health_last_scan_label.setText("Last Scan: --")

        self._recalculate_next_scan_label()

    def _recalculate_next_scan_label(self) -> None:
        if not getattr(self, "_active_health_anchor_date", None):
            self.health_next_scan_label.setText("Next Scan: --")
            return

        schedule_type = self.health_schedule_type_combo.currentText()
        anchor_date = self._active_health_anchor_date.date()
        today_utc = datetime.now(timezone.utc).date()
        next_date = self._compute_next_scan_date()
        if next_date is None:
            self.health_next_scan_label.setText("Next Scan: --")
            return

        if next_date == today_utc:
            display = "Today"
        elif next_date == today_utc + timedelta(days=1):
            display = "Tomorrow"
        else:
            if schedule_type == "Weekly":
                display = next_date.strftime("%A")
            else:
                display = next_date.isoformat()

        self.health_next_scan_label.setText(f"Next Scan: {display}")
        self._check_overdue_scan_prompt()

    def _empty_library_stats_total(self):
        return {
            "scanned_files": 0,
            "files_with_issues": 0,
            "container_not_allowed": 0,
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
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def _merge_library_stats_delta(self, delta):
        # Merge integer counters.
        for key in (
            "scanned_files",
            "files_with_issues",
            "container_not_allowed",
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
            "cache_hits",
            "cache_misses",
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
        s.append(
            "Container not allowed: "
            f"{self.library_stats_total['container_not_allowed']}"
        )
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
        cache_hits = int(self.library_stats_total.get("cache_hits", 0) or 0)
        cache_misses = int(self.library_stats_total.get("cache_misses", 0) or 0)
        cache_total = cache_hits + cache_misses
        if cache_total:
            s.append(
                f"Cache hit rate: {cache_hits}/{cache_total} "
                f"({(cache_hits / cache_total) * 100:.1f}%)"
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
