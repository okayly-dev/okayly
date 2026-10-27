"""SQLite storage. One connection, guarded by a re-entrant lock; transactions nest."""
import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, ord INTEGER, platform TEXT, stars INTEGER, who TEXT, date TEXT, text TEXT, reply TEXT
);
CREATE TABLE IF NOT EXISTS writes (idem TEXT PRIMARY KEY, review_id TEXT, applied_at REAL);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, review_id TEXT, kind TEXT, state TEXT, reason TEXT, attempt INTEGER,
  before_json TEXT, after_json TEXT, hash TEXT, idem TEXT, provider TEXT, handoff INTEGER DEFAULT 0,
  priority TEXT, first_draft_json TEXT, created_at REAL, expires_at REAL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, plain TEXT, detail TEXT,
  proposal_id TEXT, prev TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, model TEXT, purpose TEXT,
  input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER, cost_usd REAL
);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._depth = 0
        self.conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        """Outermost call opens the transaction; nested calls join it."""
        with self.lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    def one(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def run(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args)
