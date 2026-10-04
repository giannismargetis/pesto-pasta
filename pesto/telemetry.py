"""Persistent telemetry (SQLite, WAL) written off the critical path.

All writes go through one background writer thread, so a slow disk can never
delay text appearing on screen. Readers (dashboard, analysis scripts) open
their own connections; WAL lets them read while the writer appends.

Schema v2 is documented in docs/EVALUATION.md#telemetry-schema. Legacy
``transcriptions`` rows from PESTO v5 / PASTA v2 are imported once, flagged
``legacy = 1`` (their latency column measured engine time only, so they are
excluded from latency analyses).
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import paths
from .log import get_logger

log = get_logger("telemetry")

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS interactions (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,          -- ISO local time of key press / speech onset
    session_id      TEXT,
    participant     TEXT DEFAULT '',
    condition       TEXT DEFAULT '',
    input_mode      TEXT,                   -- ptt | vad
    kind            TEXT,                   -- dictation | command
    outcome         TEXT,                   -- inserted | empty | cancelled | failed | command
    engine          TEXT, model TEXT, device TEXT,
    language_mode   TEXT, language TEXT, language_prob REAL,
    audio_ms        REAL,                   -- recorded audio incl. pre-roll
    speech_ms       REAL,                   -- VAD-estimated speech
    text            TEXT, words INTEGER, chars INTEGER,
    target_app      TEXT, inject_method TEXT,
    -- latency decomposition (ms). release = PTT release or VAD endpoint.
    hold_ms             REAL,               -- press -> release
    queue_ms            REAL,               -- release -> ASR start (waiting for engine / preview)
    gate_ms             REAL,               -- speech gate (VAD) cost
    asr_ms              REAL,               -- engine time
    route_ms            REAL,
    added_delay_ms      REAL,               -- experimental manipulation (0 normally)
    inject_ms           REAL,
    release_to_text_ms  REAL,               -- system latency: release -> text injected
    speech_end_to_text_ms REAL,             -- user-perceived: last speech -> text injected
    preview_count       INTEGER,
    first_preview_ms    REAL,               -- press -> first live preview text
    error           TEXT DEFAULT '',
    marks_json      TEXT,                   -- full timeline (ms since press)
    legacy          INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_interactions_started ON interactions(started_at);

CREATE TABLE IF NOT EXISTS agent_runs (
    id              TEXT PRIMARY KEY,
    interaction_id  TEXT,
    started_at      TEXT NOT NULL,
    utterance       TEXT,
    parser          TEXT,                   -- grammar | llm | none
    plan_json       TEXT,
    status          TEXT,                   -- completed | failed | cancelled | rejected | not_understood | needs_confirmation
    steps           INTEGER,
    verified_steps  INTEGER,
    understand_ms   REAL, total_ms REAL,
    error           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agent_steps (
    run_id          TEXT, idx INTEGER,
    action          TEXT, args_json TEXT, risk TEXT, confidence REAL,
    gate            TEXT,                   -- auto | confirmed | declined | denied
    exec_ok         INTEGER, verification TEXT, evidence_json TEXT,
    exec_ms         REAL, verify_ms REAL, message TEXT,
    PRIMARY KEY (run_id, idx)
);

CREATE TABLE IF NOT EXISTS trials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    study           TEXT, participant TEXT, condition TEXT, block INTEGER, trial INTEGER,
    stimulus        TEXT, response TEXT,
    started_at      TEXT, first_input_ms REAL, completed_ms REAL,
    keystrokes      INTEGER, backspaces INTEGER, utterances INTEGER,
    wpm             REAL, msd_error REAL, cer REAL,
    data_json       TEXT
);

CREATE TABLE IF NOT EXISTS questionnaires (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    study           TEXT, participant TEXT, condition TEXT, instrument TEXT,
    answers_json    TEXT, score REAL, created_at TEXT
);
"""

INTERACTION_COLUMNS = (
    "id started_at session_id participant condition input_mode kind outcome engine model device language_mode "
    "language language_prob audio_ms speech_ms text words chars target_app inject_method hold_ms queue_ms gate_ms "
    "asr_ms route_ms added_delay_ms inject_ms release_to_text_ms speech_end_to_text_ms preview_count "
    "first_preview_ms error marks_json"
).split()


def connect(path: Path = paths.DB_PATH, readonly: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), timeout=10.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


class Telemetry:
    def __init__(self, path: Path = paths.DB_PATH) -> None:
        self.path = path
        self._q: queue.Queue[Callable[[sqlite3.Connection], Any] | None] = queue.Queue()
        conn = connect(path)
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
        self._import_legacy(conn)
        conn.close()
        self._thread = threading.Thread(target=self._writer, name="TelemetryWriter", daemon=True)
        self._thread.start()

    def _writer(self) -> None:
        conn = connect(self.path)
        while True:
            job = self._q.get()
            if job is None:
                break
            try:
                job(conn)
                conn.commit()
            except Exception:
                log.exception("telemetry write failed")
        conn.close()

    def submit(self, fn: Callable[[sqlite3.Connection], Any]) -> None:
        self._q.put(fn)

    def flush(self, timeout: float = 5.0) -> None:
        done = threading.Event()
        self._q.put(lambda conn: done.set())
        done.wait(timeout)

    def close(self) -> None:
        self.flush()
        self._q.put(None)
        self._thread.join(timeout=5.0)

    # -- writers ---------------------------------------------------------------------------
    def record_interaction(self, row: dict[str, Any]) -> None:
        values = [row.get(c) for c in INTERACTION_COLUMNS]
        sql = f"INSERT OR REPLACE INTO interactions ({','.join(INTERACTION_COLUMNS)}) VALUES ({','.join('?' * len(values))})"
        self.submit(lambda conn: conn.execute(sql, values))

    def record_agent_run(self, run: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run["id"], run.get("interaction_id"), run["started_at"], run.get("utterance"), run.get("parser"),
                 json.dumps(run.get("plan", []), ensure_ascii=False), run.get("status"), run.get("steps", 0),
                 run.get("verified_steps", 0), run.get("understand_ms"), run.get("total_ms"), run.get("error", "")),
            )
            for i, s in enumerate(steps):
                conn.execute(
                    "INSERT OR REPLACE INTO agent_steps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run["id"], i, s.get("action"), json.dumps(s.get("args", {}), ensure_ascii=False), s.get("risk"),
                     s.get("confidence"), s.get("gate"), int(bool(s.get("exec_ok"))), s.get("verification"),
                     json.dumps(s.get("evidence", {}), ensure_ascii=False, default=str), s.get("exec_ms"),
                     s.get("verify_ms"), s.get("message", "")),
                )

        self.submit(write)

    def record_trial(self, row: dict[str, Any]) -> None:
        cols = list(row)
        self.submit(lambda conn: conn.execute(
            f"INSERT INTO trials ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols]))

    def record_questionnaire(self, row: dict[str, Any]) -> None:
        cols = list(row)
        self.submit(lambda conn: conn.execute(
            f"INSERT INTO questionnaires ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [row[c] for c in cols]))

    # -- legacy import ---------------------------------------------------------------------
    def _import_legacy(self, conn: sqlite3.Connection) -> None:
        if conn.execute("SELECT value FROM meta WHERE key='legacy_imported'").fetchone():
            return
        imported = 0
        for legacy in paths.LEGACY_DB_PATHS:
            if not legacy.exists():
                continue
            try:
                old = sqlite3.connect(f"file:{legacy.as_posix()}?mode=ro", uri=True)
                old.row_factory = sqlite3.Row
                rows = old.execute("SELECT * FROM transcriptions").fetchall()
                old.close()
            except sqlite3.Error as exc:
                log.warning("legacy import from %s skipped: %s", legacy, exc)
                continue
            for r in rows:
                started = _utc_to_local(str(r["created_at"]))
                conn.execute(
                    "INSERT OR IGNORE INTO interactions (id, started_at, kind, outcome, engine, language, audio_ms, "
                    "text, words, chars, asr_ms, legacy) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (f"legacy-{legacy.stem}-{r['id']}", started, "dictation", "inserted", r["engine"],
                     r["language"], (r["duration_seconds"] or 0) * 1000, r["text"], r["word_count"], r["char_count"],
                     r["latency_ms"]),
                )
                imported += 1
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('legacy_imported', ?)", (str(imported),))
        conn.commit()
        if imported:
            log.info("Imported %d legacy transcription rows", imported)


def _utc_to_local(stamp: str) -> str:
    """Old databases stored SQLite CURRENT_TIMESTAMP, which is UTC."""
    from datetime import datetime, timezone

    try:
        dt = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp


def now_iso() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"
