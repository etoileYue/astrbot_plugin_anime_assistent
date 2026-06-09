"""SQLite 数据库操作。"""

import logging
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import Alias, Interview, Subscription, WatchLog

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL UNIQUE,
    subject_name TEXT NOT NULL,
    subject_name_cn TEXT,
    status      INTEGER DEFAULT 3,
    total_eps   INTEGER,
    last_notified_ep INTEGER DEFAULT 0,
    watched_eps INTEGER DEFAULT 0,
    airing      INTEGER DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS aliases (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,
    alias       TEXT NOT NULL,
    UNIQUE(subject_id, alias)
);

CREATE TABLE IF NOT EXISTS watch_log (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    watched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source      TEXT DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS interviews (
    id          INTEGER PRIMARY KEY,
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

    async def initialize(self, data_path: str):
        data_dir = Path(data_path)
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = str(data_dir / "bangumi.db")
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        try:
            await self._db.execute(
                "ALTER TABLE subscriptions ADD COLUMN watched_eps INTEGER DEFAULT 0"
            )
        except Exception:
            pass
        try:
            await self._db.execute(
                "ALTER TABLE subscriptions ADD COLUMN airing INTEGER DEFAULT 1"
            )
        except Exception:
            pass
        await self._db.commit()
        logger.info(f"Database initialized at {self._path}")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not initialized")
        return self._db

    # === subscriptions ===

    async def add_subscription(
        self, subject_id: int, subject_name: str,
        subject_name_cn: str = "", total_eps: int = 0, status: int = 3,
        watched_eps: int = 0, airing: int = 1,
    ) -> Subscription:
        await self.conn.execute(
            """INSERT OR REPLACE INTO subscriptions
               (subject_id, subject_name, subject_name_cn, total_eps, status, watched_eps, airing)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (subject_id, subject_name, subject_name_cn, total_eps, status, watched_eps, airing),
        )
        await self.conn.commit()
        return Subscription(
            subject_id=subject_id, subject_name=subject_name,
            subject_name_cn=subject_name_cn, total_eps=total_eps, status=status,
            watched_eps=watched_eps, airing=airing,
        )

    async def remove_subscription(self, subject_id: int):
        await self.conn.execute(
            "DELETE FROM subscriptions WHERE subject_id = ?",
            (subject_id,),
        )
        await self.conn.commit()

    async def get_subscription(self, subject_id: int) -> Optional[Subscription]:
        row = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE subject_id = ?",
            (subject_id,),
        )
        if row:
            r = row[0]
            return Subscription(
                id=r[0], subject_id=r[1], subject_name=r[2],
                subject_name_cn=r[3] or "", status=r[4], total_eps=r[5] or 0,
                last_notified_ep=r[6] or 0, watched_eps=r[7] or 0,
                airing=r[8] if r[8] is not None else 1, created_at=r[9],
            )
        return None

    async def list_subscriptions(self) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions ORDER BY created_at DESC",
        )
        results = []
        for r in rows:
            results.append(Subscription(
                id=r[0], subject_id=r[1], subject_name=r[2],
                subject_name_cn=r[3] or "", status=r[4], total_eps=r[5] or 0,
                last_notified_ep=r[6] or 0, watched_eps=r[7] or 0, airing=r[8] if r[8] is not None else 1,
                created_at=r[9],
            ))
        return results

    async def get_active_subscriptions(self) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE status = 3 AND airing = 1"
        )
        results = []
        for r in rows:
            results.append(Subscription(
                id=r[0], subject_id=r[1], subject_name=r[2],
                subject_name_cn=r[3] or "", status=r[4], total_eps=r[5] or 0,
                last_notified_ep=r[6] or 0, watched_eps=r[7] or 0, airing=r[8] if r[8] is not None else 1,
                created_at=r[9],
            ))
        return results

    async def update_last_notified_ep(self, sub_id: int, episode: int):
        await self.conn.execute(
            "UPDATE subscriptions SET last_notified_ep = ? WHERE id = ?",
            (episode, sub_id),
        )
        await self.conn.commit()

    async def update_watched_eps(self, subject_id: int, episode: int):
        await self.conn.execute(
            "UPDATE subscriptions SET watched_eps = ? WHERE subject_id = ?",
            (episode, subject_id),
        )
        await self.conn.commit()

    async def update_airing(self, subject_id: int, airing: int):
        await self.conn.execute(
            "UPDATE subscriptions SET airing = ? WHERE subject_id = ?",
            (airing, subject_id),
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

    async def log_watch(self, subject_id: int, episode: int, source: str = "manual") -> WatchLog:
        cursor = await self.conn.execute(
            "INSERT INTO watch_log (subject_id, episode, source) VALUES (?, ?, ?)",
            (subject_id, episode, source),
        )
        await self.conn.commit()
        return WatchLog(id=cursor.lastrowid, subject_id=subject_id,
                        episode=episode, source=source)

    async def get_watched_eps(self) -> dict[int, int]:
        """返回 {subject_id: max_watched_episode} 映射。"""
        rows = await self.conn.execute_fetchall(
            "SELECT subject_id, MAX(episode) FROM watch_log GROUP BY subject_id"
        )
        return {r[0]: r[1] for r in rows}

    # === interviews ===

    async def save_interview(self, subject_id: int, episode: int,
                             question: str, answer: str = "", round_num: int = 1) -> Interview:
        cursor = await self.conn.execute(
            "INSERT INTO interviews (subject_id, episode, question, answer, round) VALUES (?, ?, ?, ?, ?)",
            (subject_id, episode, question, answer, round_num),
        )
        await self.conn.commit()
        return Interview(id=cursor.lastrowid, subject_id=subject_id,
                         episode=episode, question=question, answer=answer, round=round_num)

    async def get_interviews(self, subject_id: int, episode: int) -> list[Interview]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM interviews WHERE subject_id = ? AND episode = ? ORDER BY round",
            (subject_id, episode),
        )
        return [Interview(id=r[0], subject_id=r[1], episode=r[2],
                          question=r[3], answer=r[4], round=r[5], created_at=r[6]) for r in rows]

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
