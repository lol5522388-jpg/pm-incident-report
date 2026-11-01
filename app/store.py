"""案件以 JSON 存在 SQLite。版本全文都在 body 裡，方便整份取回。"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        self._query(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                phone TEXT,
                body TEXT NOT NULL
            )
            """
        )

    def _query(self, sql: str, params: tuple = (), fetch: str | None = None):
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(sql, params)
                row = cursor.fetchone() if fetch == "one" else None
                conn.commit()
                return row
            finally:
                conn.close()

    def save(self, case: dict) -> None:
        body = json.dumps(case, ensure_ascii=False)
        self._query(
            """
            INSERT INTO cases(id, phone, body) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET phone=excluded.phone, body=excluded.body
            """,
            (case["id"], case.get("phone"), body),
        )

    def get(self, case_id: str) -> dict | None:
        row = self._query("SELECT body FROM cases WHERE id = ?", (case_id,), "one")
        if not row:
            return None
        return json.loads(row[0])

    def latest_phone(self, phone: str) -> dict | None:
        row = self._query(
            "SELECT body FROM cases WHERE phone = ? ORDER BY rowid DESC LIMIT 1",
            (phone,),
            "one",
        )
        if not row:
            return None
        return json.loads(row[0])
