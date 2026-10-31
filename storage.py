"""Transactional, session-isolated SQLite storage using only the standard library."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock

from game import new_state, rollover, validate_state


class Store:
    """One row per opaque browser session; callbacks run inside a write transaction."""

    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            database = Path(self.path)
            database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Set privacy permissions before SQLite creates its WAL sidecars.
            database.touch(mode=0o600, exist_ok=True)
            database.chmod(0o600)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA busy_timeout = 15000")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS player_state (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @staticmethod
    def _session(session_id):
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            raise ValueError("Invalid session identifier")
        return session_id

    def _read(self, session_id):
        row = self._db.execute("SELECT payload FROM player_state WHERE session_id = ?", (session_id,)).fetchone()
        state = json.loads(row[0]) if row else new_state()
        validate_state(state)
        previous_daily = (state["date"], tuple(state["done"]), state["reward_count"])
        rollover(state)
        changed = row is None or previous_daily != (state["date"], tuple(state["done"]), state["reward_count"])
        return state, changed

    def _write(self, session_id, state):
        validate_state(state)
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self._db.execute(
            "INSERT INTO player_state (session_id, payload) VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET payload = excluded.payload",
            (session_id, payload),
        )

    def get(self, session_id):
        """Return detached state, creating it or persisting daily rollover as needed."""
        session_id = self._session(session_id)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                state, changed = self._read(session_id)
                if changed:
                    self._write(session_id, state)
                self._db.execute("COMMIT")
                return deepcopy(state)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def mutate(self, session_id, callback):
        """Serialize read/modify/write and roll back if callback or validation fails."""
        session_id = self._session(session_id)
        if not callable(callback):
            raise ValueError("A mutation callback is required")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                state, _ = self._read(session_id)
                result = callback(state)
                self._write(session_id, state)
                self._db.execute("COMMIT")
                return deepcopy(state), result
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
