from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class MaatDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def initialize(self) -> None:
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY,
                    token TEXT,
                    group_name TEXT,
                    last_name TEXT,
                    first_name TEXT,
                    animal TEXT,
                    heuristic_name TEXT,
                    state TEXT,
                    submitted_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    canceled_at TEXT,
                    score_total REAL,
                    valid_instances INTEGER,
                    failed_instances INTEGER,
                    total_instances INTEGER,
                    total_runtime_seconds REAL,
                    status_json TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS instance_runs (
                    submission_id TEXT,
                    instance TEXT,
                    state TEXT,
                    score REAL,
                    nb_words REAL,
                    mean_curvature REAL,
                    runtime_seconds REAL,
                    returncode INTEGER,
                    stdout_url TEXT,
                    stderr_url TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (submission_id, instance)
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_submissions_token ON submissions(token)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_submissions_group_state ON submissions(group_name, state)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_instance_runs_instance_state ON instance_runs(instance, state)")

    def sync_submission(self, status: dict[str, Any]) -> None:
        if not status.get("submission_id"):
            return
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO submissions (
                    submission_id, token, group_name, last_name, first_name, animal,
                    heuristic_name, state, submitted_at, started_at, finished_at, canceled_at,
                    score_total, valid_instances, failed_instances, total_instances,
                    total_runtime_seconds, status_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    token=excluded.token,
                    group_name=excluded.group_name,
                    last_name=excluded.last_name,
                    first_name=excluded.first_name,
                    animal=excluded.animal,
                    heuristic_name=excluded.heuristic_name,
                    state=excluded.state,
                    submitted_at=excluded.submitted_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    canceled_at=excluded.canceled_at,
                    score_total=excluded.score_total,
                    valid_instances=excluded.valid_instances,
                    failed_instances=excluded.failed_instances,
                    total_instances=excluded.total_instances,
                    total_runtime_seconds=excluded.total_runtime_seconds,
                    status_json=excluded.status_json
                """,
                (
                    str(status.get("submission_id")),
                    status.get("token"),
                    status.get("group"),
                    status.get("last_name"),
                    status.get("first_name"),
                    status.get("animal"),
                    status.get("heuristic_name"),
                    status.get("status"),
                    status.get("submitted_at"),
                    status.get("started_at"),
                    status.get("finished_at"),
                    status.get("canceled_at"),
                    _float_or_none(status.get("score_total")),
                    _int_or_none(status.get("valid_instances")),
                    _int_or_none(status.get("failed_instances")),
                    _int_or_none(status.get("total_instances")),
                    _float_or_none(status.get("total_runtime_seconds")),
                    json.dumps(status, ensure_ascii=False),
                ),
            )
            for row in status.get("instances", []) or []:
                if not row.get("instance"):
                    continue
                con.execute(
                    """
                    INSERT INTO instance_runs (
                        submission_id, instance, state, score, nb_words, mean_curvature,
                        runtime_seconds, returncode, stdout_url, stderr_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(submission_id, instance) DO UPDATE SET
                        state=excluded.state,
                        score=excluded.score,
                        nb_words=excluded.nb_words,
                        mean_curvature=excluded.mean_curvature,
                        runtime_seconds=excluded.runtime_seconds,
                        returncode=excluded.returncode,
                        stdout_url=excluded.stdout_url,
                        stderr_url=excluded.stderr_url,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        str(status.get("submission_id")),
                        row.get("instance"),
                        row.get("status"),
                        _float_or_none(row.get("score")),
                        _float_or_none(row.get("nb_words")),
                        _float_or_none(row.get("mean_curvature")),
                        _float_or_none(row.get("runtime_seconds")),
                        _int_or_none(row.get("returncode")),
                        row.get("stdout_url"),
                        row.get("stderr_url"),
                    ),
                )

    def sync_all(self, statuses: Iterable[dict[str, Any]]) -> None:
        for status in statuses:
            self.sync_submission(status)

    def delete_submission(self, submission_id: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM instance_runs WHERE submission_id=?", (submission_id,))
            con.execute("DELETE FROM submissions WHERE submission_id=?", (submission_id,))


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
