"""SQLite 数据库操作。"""

import logging
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import Alias, Interview, Subscription, User, WatchLog

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    qq_id       TEXT UNIQUE NOT NULL,
    bangumi_token TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    subject_id  INTEGER NOT NULL,
    subject_name TEXT NOT NULL,
    subject_name_cn TEXT,
    status      INTEGER DEFAULT 3,
    total_eps   INTEGER,
    last_notified_ep INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, subject_id)
);

CREATE TABLE IF NOT EXISTS aliases (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,
    alias       TEXT NOT NULL,
    UNIQUE(subject_id, alias)
);

CREATE TABLE IF NOT EXISTS watch_log (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    watched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source      TEXT DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS interviews (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT,
    round       INTEGER DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


class Database:
    def __init__(self):
        self._db: Optional[aiosqlite.Connection] = None
        self._path: str = ""

    async def initialize(self, config):
        data_dir = Path("data") / "plugin_data" / "bangumi"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = str(data_dir / "bangumi.db")
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info(f"Database initialized at {self._path}")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not initialized")
        return self._db

    # === users ===

    async def ensure_user(self, qq_id: str) -> User:
        row = await self.conn.execute_fetchall("SELECT * FROM users WHERE qq_id = ?", (qq_id,))
        if row:
            r = row[0]
            return User(id=r[0], qq_id=r[1], bangumi_token=r[2] or "", created_at=r[3])
        await self.conn.execute("INSERT INTO users (qq_id) VALUES (?)", (qq_id,))
        await self.conn.commit()
        return User(qq_id=qq_id)

    async def get_user(self, qq_id: str) -> Optional[User]:
        row = await self.conn.execute_fetchall("SELECT * FROM users WHERE qq_id = ?", (qq_id,))
        if row:
            r = row[0]
            return User(id=r[0], qq_id=r[1], bangumi_token=r[2] or "", created_at=r[3])
        return None

    # === subscriptions ===

    async def add_subscription(
        self, user_id: int, subject_id: int, subject_name: str,
        subject_name_cn: str = "", total_eps: int = 0, status: int = 3,
    ) -> Subscription:
        await self.conn.execute(
            """INSERT OR REPLACE INTO subscriptions
               (user_id, subject_id, subject_name, subject_name_cn, total_eps, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, subject_id, subject_name, subject_name_cn, total_eps, status),
        )
        await self.conn.commit()
        return Subscription(
            user_id=user_id, subject_id=subject_id, subject_name=subject_name,
            subject_name_cn=subject_name_cn, total_eps=total_eps, status=status,
        )

    async def remove_subscription(self, user_id: int, subject_id: int):
        await self.conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND subject_id = ?",
            (user_id, subject_id),
        )
        await self.conn.commit()

    async def get_subscription(self, user_id: int, subject_id: int) -> Optional[Subscription]:
        row = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE user_id = ? AND subject_id = ?",
            (user_id, subject_id),
        )
        if row:
            r = row[0]
            return Subscription(
                id=r[0], user_id=r[1], subject_id=r[2], subject_name=r[3],
                subject_name_cn=r[4] or "", status=r[5], total_eps=r[6] or 0,
                last_notified_ep=r[7] or 0, created_at=r[8],
            )
        return None

    async def list_subscriptions(self, user_id: int) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        results = []
        for r in rows:
            results.append(Subscription(
                id=r[0], user_id=r[1], subject_id=r[2], subject_name=r[3],
                subject_name_cn=r[4] or "", status=r[5], total_eps=r[6] or 0,
                last_notified_ep=r[7] or 0, created_at=r[8],
            ))
        return results

    async def get_active_subscriptions(self) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE status = 3"
        )
        results = []
        for r in rows:
            results.append(Subscription(
                id=r[0], user_id=r[1], subject_id=r[2], subject_name=r[3],
                subject_name_cn=r[4] or "", status=r[5], total_eps=r[6] or 0,
                last_notified_ep=r[7] or 0, created_at=r[8],
            ))
        return results

    async def update_last_notified_ep(self, sub_id: int, episode: int):
        await self.conn.execute(
            "UPDATE subscriptions SET last_notified_ep = ? WHERE id = ?",
            (episode, sub_id),
        )
        await self.conn.commit()

    # === aliases ===

    async def add_alias(self, subject_id: int, alias: str):
        await self.conn.execute(
            "INSERT OR IGNORE INTO aliases (subject_id, alias) VALUES (?, ?)",
            (subject_id, alias),
        )
        await self.conn.commit()

    async def find_by_alias(self, alias: str) -> Optional[Alias]:
        row = await self.conn.execute_fetchall(
            "SELECT * FROM aliases WHERE alias = ?", (alias,)
        )
        if row:
            r = row[0]
            return Alias(id=r[0], subject_id=r[1], alias=r[2])
        return None

    async def get_aliases(self, subject_id: int) -> list[Alias]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM aliases WHERE subject_id = ?", (subject_id,)
        )
        return [Alias(id=r[0], subject_id=r[1], alias=r[2]) for r in rows]

    # === watch_log ===

    async def log_watch(self, user_id: int, subject_id: int, episode: int, source: str = "manual") -> WatchLog:
        cursor = await self.conn.execute(
            "INSERT INTO watch_log (user_id, subject_id, episode, source) VALUES (?, ?, ?, ?)",
            (user_id, subject_id, episode, source),
        )
        await self.conn.commit()
        return WatchLog(id=cursor.lastrowid, user_id=user_id, subject_id=subject_id,
                        episode=episode, source=source)

    # === interviews ===

    async def save_interview(self, user_id: int, subject_id: int, episode: int,
                             question: str, answer: str = "", round_num: int = 1) -> Interview:
        cursor = await self.conn.execute(
            "INSERT INTO interviews (user_id, subject_id, episode, question, answer, round) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, subject_id, episode, question, answer, round_num),
        )
        await self.conn.commit()
        return Interview(id=cursor.lastrowid, user_id=user_id, subject_id=subject_id,
                         episode=episode, question=question, answer=answer, round=round_num)

    async def get_interviews(self, user_id: int, subject_id: int, episode: int) -> list[Interview]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM interviews WHERE user_id = ? AND subject_id = ? AND episode = ? ORDER BY round",
            (user_id, subject_id, episode),
        )
        return [Interview(id=r[0], user_id=r[1], subject_id=r[2], episode=r[3],
                          question=r[4], answer=r[5], round=r[6], created_at=r[7]) for r in rows]

    # === task_state ===

    async def get_task_state(self, key: str) -> Optional[str]:
        row = await self.conn.execute_fetchall(
            "SELECT value FROM task_state WHERE key = ?", (key,)
        )
        return row[0][0] if row else None

    async def set_task_state(self, key: str, value: str):
        await self.conn.execute(
            "INSERT OR REPLACE INTO task_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.conn.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None
