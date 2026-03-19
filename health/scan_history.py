import json
import os
from datetime import datetime, timezone
from typing import Any


DEFAULT_HISTORY_FILENAME = "scan_history.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ScanHistory:
    """
    Persist scan summaries (and enough issue detail to restore the UI).
    """

    def __init__(self, history_path: str | None = None, max_entries: int = 100):
        if history_path is None:
            # Keep history file at repo root for stable UX.
            repo_root = os.path.dirname(os.path.dirname(__file__))
            history_path = os.path.join(repo_root, DEFAULT_HISTORY_FILENAME)
        self.history_path = history_path
        self.max_entries = max_entries

        self._data: dict[str, Any] = {"version": 1, "scans": []}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        try:
            if os.path.exists(self.history_path):
                with open(self.history_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and isinstance(loaded.get("scans"), list):
                    self._data = loaded
        except Exception:
            # Corrupt history should not break scanning.
            self._data = {"version": 1, "scans": []}

    def scans(self) -> list[dict[str, Any]]:
        self.load()
        # newest first
        return sorted(
            (s for s in (self._data.get("scans") or []) if isinstance(s, dict)),
            key=lambda s: s.get("completed_at") or s.get("started_at") or "",
            reverse=True,
        )

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        self.load()
        for s in self._data.get("scans") or []:
            if isinstance(s, dict) and s.get("id") == scan_id:
                return s
        return None

    def add_scan(self, scan_record: dict[str, Any]) -> str:
        self.load()

        # Basic shape enforcement.
        if not isinstance(scan_record, dict):
            raise TypeError("scan_record must be a dict")

        scan_id = scan_record.get("id") or f"scan_{_utc_now_iso()}"
        scan_record["id"] = scan_id
        if not scan_record.get("started_at"):
            scan_record["started_at"] = _utc_now_iso()
        if not scan_record.get("completed_at"):
            scan_record["completed_at"] = _utc_now_iso()
        if "bad_files" not in scan_record:
            scan_record["bad_files"] = []

        self._data.setdefault("scans", []).append(scan_record)

        # Trim old entries (keep newest).
        self._data["scans"] = sorted(
            self._data["scans"],
            key=lambda s: (s.get("completed_at") or s.get("started_at") or ""),
            reverse=True,
        )[: self.max_entries]

        self._save()
        return scan_id

    def _save(self) -> None:
        # Best effort persistence; don't crash the app if disk is read-only.
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

