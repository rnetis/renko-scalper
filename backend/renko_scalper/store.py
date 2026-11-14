from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT UNIQUE NOT NULL,
  created_ms INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  style TEXT NOT NULL,
  side INTEGER NOT NULL,
  score INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  payload TEXT NOT NULL,
  trade TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sig_sym ON signals(symbol, style, created_ms);
"""


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def insert(self, key: str, payload: dict, trade: dict) -> Optional[int]:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO signals(key,created_ms,symbol,style,side,score,status,payload,trade) VALUES (?,?,?,?,?,?,?,?,?)",
                    (key, int(time.time() * 1000), payload["symbol"], payload["style"], payload["side"],
                     payload["score"], "open", json.dumps(payload), json.dumps(trade)),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def update(self, sid: int, status: str, trade: dict) -> None:
        with self._lock:
            self._conn.execute("UPDATE signals SET status=?, trade=? WHERE id=?", (status, json.dumps(trade), sid))
            self._conn.commit()

    def _row(self, r) -> dict:
        return {"id": r["id"], "created_ms": r["created_ms"], "status": r["status"],
                "payload": json.loads(r["payload"]), "trade": json.loads(r["trade"])}

    def list(self, since_id: int = 0, limit: int = 50, status: Optional[str] = None) -> list:
        q, args = "SELECT * FROM signals WHERE id > ?", [since_id]
        if status == "active":
            q += " AND status IN ('open','tp1')"
        elif status:
            q += " AND status = ?"
            args.append(status)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [self._row(r) for r in self._conn.execute(q, args).fetchall()]

    def get(self, sid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
        return self._row(r) if r else None

    def last_created_ms(self, symbol: str, style: str) -> int:
        with self._lock:
            r = self._conn.execute(
                "SELECT MAX(created_ms) m FROM signals WHERE symbol=? AND style=?", (symbol, style)).fetchone()
        return int(r["m"] or 0)

    def closed(self, limit: int = 200) -> list:
        """Most recent finished trades (any exit reason), newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE status NOT IN ('open','tp1') ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]
