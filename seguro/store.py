"""SQLite-база результатів: історія перевірок, ручні статуси (shortlisted/bought/skipped).

Завдяки їй домен, який уже перевіряли, не перевіряється знову при наступному
завантаженні дроп-листа (вони повторюються день у день) — головна економія запитів.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .models import Result

MANUAL_STATUSES = ("shortlisted", "bought", "skipped")

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    domain        TEXT PRIMARY KEY,
    source        TEXT,
    status        TEXT,
    score         REAL,
    rejected_by   TEXT,
    reject_reason TEXT,
    flags         TEXT,
    metrics       TEXT,
    evaluated_at  REAL,
    manual_status TEXT,
    note          TEXT
)
"""

UPSERT = """
INSERT INTO domains (domain, source, status, score, rejected_by, reject_reason, flags, metrics, evaluated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(domain) DO UPDATE SET
    source = excluded.source, status = excluded.status, score = excluded.score,
    rejected_by = excluded.rejected_by, reject_reason = excluded.reject_reason,
    flags = excluded.flags, metrics = excluded.metrics, evaluated_at = excluded.evaluated_at
"""


class Store:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def recently_evaluated(self, domains: Iterable[str], days: float) -> set[str]:
        cutoff = time.time() - days * 86400
        found: set[str] = set()
        pool = list(domains)
        for i in range(0, len(pool), 500):
            chunk = pool[i:i + 500]
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT domain FROM domains WHERE evaluated_at >= ? AND domain IN ({marks})",
                [cutoff, *chunk],
            )
            found.update(r[0] for r in rows)
        return found

    def save(self, results: Iterable[Result]) -> int:
        now = time.time()
        rows = [
            (
                r.domain, r.source, "rejected" if r.rejected else "candidate", r.score,
                r.rejected_by, r.reject_reason, ",".join(r.flags),
                json.dumps(r.metrics, ensure_ascii=False, default=str), now,
            )
            for r in results
        ]
        self.conn.executemany(UPSERT, rows)
        self.conn.commit()
        return len(rows)

    def mark(self, domain: str, manual_status: str | None, note: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO domains (domain, manual_status, note) VALUES (?, ?, ?) "
            "ON CONFLICT(domain) DO UPDATE SET manual_status = excluded.manual_status, "
            "note = COALESCE(excluded.note, domains.note)",
            (domain, manual_status, note),
        )
        self.conn.commit()

    def rows(self, status: str | None = None, manual_status: str | None = None,
             min_score: float | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if manual_status:
            where.append("manual_status = ?")
            params.append(manual_status)
        if min_score is not None:
            where.append("score >= ?")
            params.append(min_score)
        sql = "SELECT * FROM domains"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (status = 'candidate') DESC, score DESC, domain"
        if limit:
            sql += f" LIMIT {int(limit)}"
        out = []
        for row in self.conn.execute(sql, params):
            item = dict(row)
            item["metrics"] = json.loads(item["metrics"]) if item.get("metrics") else {}
            item["flags"] = [f for f in (item.get("flags") or "").split(",") if f]
            out.append(item)
        return out

    def summary(self) -> dict[str, Any]:
        def counts(sql: str) -> dict[str, int]:
            return {str(k or ""): v for k, v in self.conn.execute(sql)}

        return {
            "total": self.conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0],
            "by_status": counts("SELECT status, COUNT(*) FROM domains GROUP BY status"),
            "by_manual": counts("SELECT manual_status, COUNT(*) FROM domains "
                                "WHERE manual_status IS NOT NULL GROUP BY manual_status"),
            "by_stage": counts("SELECT rejected_by, COUNT(*) FROM domains "
                               "WHERE rejected_by IS NOT NULL GROUP BY rejected_by ORDER BY 2 DESC"),
        }
