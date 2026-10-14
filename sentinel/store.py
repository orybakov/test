from __future__ import annotations
import sqlite3
from contextlib import contextmanager
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source TEXT NOT NULL,
 external_id TEXT,
 title TEXT NOT NULL,
 message TEXT NOT NULL,
 requested_level TEXT NOT NULL,
 priority TEXT NOT NULL,
 speech TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL,
 audio_file TEXT,
 error TEXT,
 attempts INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL,
 processed_at INTEGER,
 UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_status_created ON events(status, created_at);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA journal_mode=WAL")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def recover(self):
        with self.conn() as c:
            c.execute("UPDATE events SET status='queued' WHERE status='processing'")

    def insert(self, source: str, external_id: str | None, title: str, message: str,
               level: str, priority: str, speech: str):
        now = int(time.time())
        status = "silent" if priority == "silent" else "digest" if priority == "normal" else "queued"
        with self.conn() as c:
            cur = c.execute("""INSERT OR IGNORE INTO events
              (source,external_id,title,message,requested_level,priority,speech,status,created_at)
              VALUES (?,?,?,?,?,?,?,?,?)""",
              (source, external_id, title, message, level, priority, speech, status, now))
            created = bool(cur.rowcount)
            if created:
                event = c.execute("SELECT * FROM events WHERE id=?", (cur.lastrowid,)).fetchone()
            else:
                event = c.execute("SELECT * FROM events WHERE source=? AND external_id=?",
                                  (source, external_id)).fetchone()
        return dict(event), created

    def get(self, event_id: int):
        with self.conn() as c:
            row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 60):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self):
        with self.conn() as c:
            rows = c.execute("SELECT status, COUNT(*) AS n FROM events GROUP BY status").fetchall()
            total = c.execute("SELECT count(*) FROM events").fetchone()[0]
            priorities = c.execute("SELECT priority,COUNT(*) AS n FROM events GROUP BY priority").fetchall()
        return {"total": total, **{r["status"]: r["n"] for r in rows},
                **{f"priority_{r['priority']}": r['n'] for r in priorities}}

    def pending(self):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM events WHERE status='queued' ORDER BY id LIMIT 10").fetchall()
        return [dict(r) for r in rows]

    def update(self, event_id: int, **kwargs):
        if not kwargs:
            return
        allowed = {"priority", "speech", "status", "audio_file", "error", "attempts", "processed_at"}
        if not set(kwargs).issubset(allowed):
            raise ValueError("Unsupported update field")
        columns = ",".join(f"{k}=?" for k in kwargs)
        with self.conn() as c:
            c.execute(f"UPDATE events SET {columns} WHERE id=?", [*kwargs.values(), event_id])

    def digest_items(self):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM events WHERE status='digest' ORDER BY id LIMIT 30").fetchall()
        return [dict(r) for r in rows]

    def digest_mark(self, ids: list[int]):
        if not ids:
            return
        with self.conn() as c:
            c.executemany("UPDATE events SET status='digested',processed_at=? WHERE id=?",
                          [(int(time.time()), i) for i in ids])
