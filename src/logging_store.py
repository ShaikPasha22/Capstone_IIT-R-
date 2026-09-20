"""Decision log: every automated decision must be reconstructable months
later. One record per pipeline stage per ticket, per the schema in the
Governance Framework.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id     TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    ticket_id       TEXT NOT NULL,
    stage           TEXT NOT NULL,
    prediction      TEXT,
    confidence      REAL,
    threshold       REAL,
    action_taken    TEXT NOT NULL,
    reason          TEXT NOT NULL,
    sources_used    TEXT,
    guardrails      TEXT,
    prompt_version  TEXT,
    requirement_ids TEXT
)
"""


class DecisionLog:
    """One SQLite connection, shared across requests. FastAPI runs sync path
    operations in a worker-thread pool, so `check_same_thread=False` plus a
    lock around every access is required -- without it, a request handled on
    a different thread than the one that opened the connection raises
    `sqlite3.ProgrammingError`, and unserialised concurrent writes to the
    same connection can otherwise corrupt the database.
    """

    def __init__(self, db_path: str = "./storage/decisions.db"):
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.connection.execute(SCHEMA)
            self.connection.commit()

    def record(
        self,
        ticket_id: str,
        stage: str,
        action_taken: str,
        reason: str,
        prediction: str | None = None,
        confidence: float | None = None,
        threshold: float | None = None,
        sources_used: list[str] | None = None,
        guardrails: dict | None = None,
        prompt_version: str = "PR-01 v1.0",
        requirement_ids: list[str] | None = None,
    ) -> str:
        decision_id = str(uuid.uuid4())
        with self._lock:
            self.connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    datetime.now(timezone.utc).isoformat(),
                    ticket_id,
                    stage,
                    prediction,
                    confidence,
                    threshold,
                    action_taken,
                    reason,
                    json.dumps(sources_used or []),
                    json.dumps(guardrails or {}),
                    prompt_version,
                    json.dumps(requirement_ids or []),
                ),
            )
            self.connection.commit()
        return decision_id

    def count_for_ticket(self, ticket_id: str) -> int:
        with self._lock:
            cur = self.connection.execute("SELECT COUNT(*) FROM decisions WHERE ticket_id = ?", (ticket_id,))
            return cur.fetchone()[0]

    def count_all(self) -> int:
        with self._lock:
            cur = self.connection.execute("SELECT COUNT(*) FROM decisions")
            return cur.fetchone()[0]

    def rows_for_ticket(self, ticket_id: str) -> list[dict]:
        """Every decision recorded for one ticket, oldest first -- the trace
        of what the pipeline did and why, for the console and for audits.
        """
        with self._lock:
            cur = self.connection.execute(
                "SELECT decision_id, created_at, stage, prediction, confidence, threshold, "
                "action_taken, reason, sources_used, guardrails, prompt_version, requirement_ids "
                "FROM decisions WHERE ticket_id = ? ORDER BY created_at ASC",
                (ticket_id,),
            )
            columns = [d[0] for d in cur.description]
            rows_raw = cur.fetchall()
        rows = []
        for row in rows_raw:
            record = dict(zip(columns, row))
            record["sources_used"] = json.loads(record["sources_used"] or "[]")
            record["guardrails"] = json.loads(record["guardrails"] or "{}")
            record["requirement_ids"] = json.loads(record["requirement_ids"] or "[]")
            rows.append(record)
        return rows
