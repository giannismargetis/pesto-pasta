import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import HOME
from .logging_setup import get_logger

log = get_logger("history")

DB_DIR = HOME / "cache"
DB_PATH = DB_DIR / "pasta_history.db"
MAX_STORAGE_BYTES = 1024 * 1024 * 1024  # 1 GB


class HistoryDB:
    def __init__(self, db_path: Path | None = None, max_bytes: int = MAX_STORAGE_BYTES) -> None:
        self.db_path = db_path or DB_PATH
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    text TEXT NOT NULL,
                    duration_seconds REAL DEFAULT 0.0,
                    latency_ms REAL DEFAULT 0.0,
                    word_count INTEGER DEFAULT 0,
                    char_count INTEGER DEFAULT 0,
                    wpm REAL DEFAULT 0.0,
                    cps REAL DEFAULT 0.0,
                    engine TEXT DEFAULT '',
                    language TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transcriptions_created_at ON transcriptions (created_at DESC)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    transcript TEXT NOT NULL,
                    task TEXT NOT NULL,
                    state_summary TEXT,
                    candidates_json TEXT,
                    probabilities_json TEXT,
                    selected_action TEXT,
                    execution_result TEXT,
                    verification_result TEXT,
                    elapsed_ms REAL DEFAULT 0.0,
                    termination_reason TEXT,
                    steps_count INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs (created_at DESC)")
            conn.commit()

    def add_entry(
        self,
        text: str,
        duration_seconds: float = 0.0,
        latency_ms: float = 0.0,
        engine: str = "",
        language: str = "",
    ) -> int | None:
        clean_text = text.strip()
        if not clean_text:
            return None

        words = len(clean_text.split())
        chars = len(clean_text)
        eff_duration = max(duration_seconds, 0.4)
        wpm = round((words / eff_duration) * 60.0, 1)
        cps = round(chars / eff_duration, 1)

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO transcriptions (
                            text, duration_seconds, latency_ms, word_count,
                            char_count, wpm, cps, engine, language
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (clean_text, duration_seconds, latency_ms, words, chars, wpm, cps, engine, language),
                    )
                    conn.commit()
                    row_id = cursor.lastrowid
                self._prune_if_needed()
                return row_id
            except Exception as exc:
                log.error("Failed to insert history record: %s", exc)
                return None

    def add_agent_run(
        self,
        run_id: str,
        transcript: str,
        task: str,
        state_summary: str = "",
        candidates: list[dict[str, Any]] | None = None,
        probabilities: list[float] | None = None,
        selected_action: str = "",
        execution_result: str = "",
        verification_result: str = "",
        elapsed_ms: float = 0.0,
        termination_reason: str = "",
        steps_count: int = 1,
        success: bool = True,
    ) -> int | None:
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO agent_runs (
                            run_id, transcript, task, state_summary,
                            candidates_json, probabilities_json, selected_action,
                            execution_result, verification_result, elapsed_ms,
                            termination_reason, steps_count, success
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            transcript,
                            task,
                            state_summary,
                            json.dumps(candidates or []),
                            json.dumps(probabilities or []),
                            selected_action,
                            execution_result,
                            verification_result,
                            elapsed_ms,
                            termination_reason,
                            steps_count,
                            1 if success else 0,
                        ),
                    )
                    conn.commit()
                    return cursor.lastrowid
            except Exception as exc:
                log.error("Failed to log agent run: %s", exc)
                return None

    def get_entries(
        self,
        limit: int = 100,
        offset: int = 0,
        search_query: str | None = None,
    ) -> list[dict]:
        with self._lock:
            try:
                with self._get_connection() as conn:
                    if search_query and search_query.strip():
                        q = f"%{search_query.strip()}%"
                        cur = conn.execute(
                            """
                            SELECT * FROM transcriptions
                            WHERE text LIKE ?
                            ORDER BY id DESC
                            LIMIT ? OFFSET ?
                            """,
                            (q, limit, offset),
                        )
                    else:
                        cur = conn.execute(
                            """
                            SELECT * FROM transcriptions
                            ORDER BY id DESC
                            LIMIT ? OFFSET ?
                            """,
                            (limit, offset),
                        )
                    return [dict(r) for r in cur.fetchall()]
            except Exception as exc:
                log.error("Failed to fetch history records: %s", exc)
                return []

    def get_agent_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.execute(
                        """
                        SELECT * FROM agent_runs
                        ORDER BY id DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    )
                    return [dict(r) for r in cur.fetchall()]
            except Exception as exc:
                log.error("Failed to fetch agent runs: %s", exc)
                return []

    def get_statistics(self) -> dict:
        with self._lock:
            try:
                with self._get_connection() as conn:
                    row = conn.execute("""
                        SELECT
                            COUNT(*) as total_count,
                            COALESCE(SUM(word_count), 0) as total_words,
                            COALESCE(SUM(char_count), 0) as total_chars,
                            COALESCE(SUM(duration_seconds), 0.0) as total_duration,
                            COALESCE(AVG(CASE WHEN duration_seconds > 0.8 THEN wpm END), 0.0) as avg_wpm
                        FROM transcriptions
                    """).fetchone()

                    today = time.strftime("%Y-%m-%d")
                    today_row = conn.execute(
                        "SELECT COALESCE(SUM(word_count), 0) as today_words, COUNT(*) as today_count FROM transcriptions WHERE created_at >= ?",
                        (today + " 00:00:00",),
                    ).fetchone()

                    agent_stats = conn.execute("""
                        SELECT
                            COUNT(*) as total_runs,
                            COALESCE(SUM(success), 0) as successful_runs,
                            COALESCE(AVG(elapsed_ms), 0.0) as avg_elapsed_ms
                        FROM agent_runs
                    """).fetchone()

                file_size = self.db_path.stat().st_size if self.db_path.exists() else 0
                return {
                    "total_count": row["total_count"] if row else 0,
                    "total_words": row["total_words"] if row else 0,
                    "total_chars": row["total_chars"] if row else 0,
                    "total_duration": row["total_duration"] if row else 0.0,
                    "avg_wpm": round(row["avg_wpm"] if row else 0.0, 1),
                    "today_words": today_row["today_words"] if today_row else 0,
                    "today_count": today_row["today_count"] if today_row else 0,
                    "total_agent_runs": agent_stats["total_runs"] if agent_stats else 0,
                    "successful_agent_runs": agent_stats["successful_runs"] if agent_stats else 0,
                    "avg_agent_ms": round(agent_stats["avg_elapsed_ms"] if agent_stats else 0.0, 1),
                    "db_size_bytes": file_size,
                    "db_size_mb": round(file_size / (1024 * 1024), 2),
                    "max_storage_mb": round(self.max_bytes / (1024 * 1024), 0),
                }
            except Exception as exc:
                log.error("Failed to compute history statistics: %s", exc)
                return {
                    "total_count": 0, "total_words": 0, "total_chars": 0, "total_duration": 0.0,
                    "avg_wpm": 0.0, "today_words": 0, "today_count": 0, "total_agent_runs": 0,
                    "successful_agent_runs": 0, "avg_agent_ms": 0.0, "db_size_bytes": 0,
                    "db_size_mb": 0.0, "max_storage_mb": 1000.0
                }

    def _prune_if_needed(self) -> None:
        try:
            if not self.db_path.exists():
                return
            current_size = self.db_path.stat().st_size
            if current_size > self.max_bytes:
                with self._get_connection() as conn:
                    count_row = conn.execute("SELECT COUNT(*) as cnt FROM transcriptions").fetchone()
                    total = count_row["cnt"] if count_row else 0
                    to_delete = max(100, int(total * 0.15))
                    conn.execute("""
                        DELETE FROM transcriptions WHERE id IN (
                            SELECT id FROM transcriptions ORDER BY id ASC LIMIT ?
                        )
                    """, (to_delete,))
                    conn.commit()
                    conn.execute("VACUUM")
        except Exception as exc:
            log.warning("Pruning check failed: %s", exc)


_instance: HistoryDB | None = None


def get_history_db() -> HistoryDB:
    global _instance
    if _instance is None:
        _instance = HistoryDB()
    return _instance
