from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.schemas_reports import (
    AnalysisReportDispositionUpdate,
    AnalysisReportItem,
    AnalysisReportPayload,
)


REPORT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "analysis_reports.sqlite3"
MAX_REPORT_INPUT_CHARS = 12_000
MAX_REPORT_JSON_BYTES = 200_000


class AnalysisReportError(Exception):
    pass


class AnalysisReportTooLargeError(AnalysisReportError):
    pass


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _connect():
    REPORT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REPORT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_reports (
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            input_text TEXT NOT NULL,
            report_json TEXT NOT NULL,
            disposition TEXT NOT NULL DEFAULT 'pending',
            disposition_note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_reports_user_updated ON analysis_reports(user_id, updated_at DESC)")


def _row_to_item(row: sqlite3.Row) -> AnalysisReportItem:
    try:
        report = json.loads(row["report_json"] or "{}")
    except json.JSONDecodeError:
        report = {}
    return AnalysisReportItem(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        input=row["input_text"],
        report=report if isinstance(report, dict) else {},
        disposition=row["disposition"] or "pending",
        disposition_note=row["disposition_note"] or "",
        updated_at=row["updated_at"],
    )


def list_analysis_reports(user_id: str) -> list[AnalysisReportItem]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM analysis_reports
            WHERE user_id = ?
            ORDER BY created_at DESC, updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [_row_to_item(row) for row in rows]


def save_analysis_report(user_id: str, payload: AnalysisReportPayload) -> AnalysisReportItem:
    if len(payload.input or "") > MAX_REPORT_INPUT_CHARS:
        raise AnalysisReportTooLargeError(f"analysis report input exceeds {MAX_REPORT_INPUT_CHARS} characters")
    now = _now_text()
    report_json = json.dumps(payload.report, ensure_ascii=False)
    if len(report_json.encode("utf-8")) > MAX_REPORT_JSON_BYTES:
        raise AnalysisReportTooLargeError(f"analysis report payload exceeds {MAX_REPORT_JSON_BYTES} bytes")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_reports (
                id, user_id, title, created_at, input_text, report_json,
                disposition, disposition_note, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, id) DO UPDATE SET
                title = excluded.title,
                created_at = excluded.created_at,
                input_text = excluded.input_text,
                report_json = excluded.report_json,
                disposition = excluded.disposition,
                disposition_note = excluded.disposition_note,
                updated_at = excluded.updated_at
            """,
            (
                payload.id,
                user_id,
                payload.title[:300],
                payload.created_at,
                payload.input,
                report_json,
                payload.disposition,
                payload.disposition_note,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM analysis_reports WHERE user_id = ? AND id = ?",
            (user_id, payload.id),
        ).fetchone()
        return _row_to_item(row)


def update_analysis_report_disposition(
    user_id: str,
    report_id: str,
    payload: AnalysisReportDispositionUpdate,
) -> AnalysisReportItem:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM analysis_reports WHERE user_id = ? AND id = ?",
            (user_id, report_id),
        ).fetchone()
        if not row:
            raise AnalysisReportError("analysis report not found")

        conn.execute(
            """
            UPDATE analysis_reports
            SET disposition = ?, disposition_note = ?, updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (payload.disposition, payload.disposition_note, _now_text(), user_id, report_id),
        )
        next_row = conn.execute(
            "SELECT * FROM analysis_reports WHERE user_id = ? AND id = ?",
            (user_id, report_id),
        ).fetchone()
        return _row_to_item(next_row)


def delete_analysis_report(user_id: str, report_id: str) -> None:
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM analysis_reports WHERE user_id = ? AND id = ?",
            (user_id, report_id),
        )
        if cursor.rowcount == 0:
            raise AnalysisReportError("analysis report not found")


def delete_analysis_reports_for_user(user_id: str) -> int:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM analysis_reports WHERE user_id = ?", (user_id,))
        return max(0, int(cursor.rowcount or 0))
