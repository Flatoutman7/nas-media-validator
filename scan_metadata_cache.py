import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from rules import analyze_file as analyze_file_uncached


def canonicalize_path_key(path: str) -> str:
    """
    Stable key across runs on Windows (case-insensitive).
    """
    if not path:
        return ""
    normalized = os.path.normpath(path).strip()
    normalized = normalized.replace("/", "\\")
    return normalized.casefold()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class FileMeta:
    size: int
    mtime_ns: int


class ScanMetadataCache:
    """
    Incremental scan cache:
    - cache entries keyed by file path
    - rescan when (size, mtime_ns) changes
    - reuse cached (issues, stats) when unchanged
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()  # sqlite connection per thread

        # Counts updated by the main thread (not worker threads),
        # but kept here for convenience if needed later.
        self.hits = 0
        self.misses = 0

        self._write_lock = threading.Lock()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        # Each worker thread gets its own connection (safe concurrency).
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path_key TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                issues_json TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                last_scan_utc TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        conn.commit()

        self._local.conn = conn
        return conn

    def _get_file_meta(self, file_path: str) -> FileMeta:
        st = os.stat(file_path)
        return FileMeta(size=int(st.st_size), mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))))

    def _load_cached(self, file_path: str, meta: FileMeta) -> tuple[list[str], dict[str, Any]] | None:
        path_key = canonicalize_path_key(file_path)
        conn = self._conn()

        cur = conn.execute(
            """
            SELECT issues_json, stats_json
            FROM files
            WHERE path_key=? AND size=? AND mtime_ns=?
            """,
            (path_key, meta.size, meta.mtime_ns),
        )
        row = cur.fetchone()
        if not row:
            return None

        issues_json, stats_json = row
        try:
            issues = json.loads(issues_json)
            stats = json.loads(stats_json)
        except Exception:
            return None

        if not isinstance(issues, list) or not isinstance(stats, dict):
            return None
        return issues, stats

    def _save_cached(
        self,
        file_path: str,
        meta: FileMeta,
        issues: list[str],
        stats: dict[str, Any],
        status: str,
    ) -> None:
        path_key = canonicalize_path_key(file_path)
        conn = self._conn()

        record = (
            path_key,
            file_path,
            int(meta.size),
            int(meta.mtime_ns),
            json.dumps(issues, ensure_ascii=False),
            json.dumps(stats, ensure_ascii=False),
            _utc_now_iso(),
            status,
        )

        # Writes are serialized to avoid "database is locked" cascades.
        with self._write_lock:
            conn.execute(
                """
                INSERT INTO files (path_key, path, size, mtime_ns, issues_json, stats_json, last_scan_utc, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path_key) DO UPDATE SET
                    path=excluded.path,
                    size=excluded.size,
                    mtime_ns=excluded.mtime_ns,
                    issues_json=excluded.issues_json,
                    stats_json=excluded.stats_json,
                    last_scan_utc=excluded.last_scan_utc,
                    status=excluded.status
                """,
                record,
            )
            conn.commit()

    def analyze_file_cached(self, file_path: str) -> tuple[list[str], dict[str, Any], bool]:
        """
        Returns (issues, stats, from_cache).
        """
        meta = self._get_file_meta(file_path)
        cached = self._load_cached(file_path, meta)
        if cached is not None:
            issues, stats = cached
            return issues, stats, True

        issues, stats = analyze_file_uncached(file_path)
        self._save_cached(file_path, meta, issues, stats, status="computed")
        return issues, stats, False

