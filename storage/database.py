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
    mal_id      INTEGER,
    schedule_weekday INTEGER,
    schedule_time TEXT,
    schedule_timezone TEXT,
    schedule_source TEXT,
    last_schedule_notified_at TEXT,
    schedule_checked INTEGER DEFAULT 0,
    schedule_checked_at TEXT,
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
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    episode_start INTEGER
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
        # SQLite 不支持 ADD COLUMN IF NOT EXISTS；逐项尝试使升级迁移可重复执行。
        for column, definition in (
            ("watched_eps", "INTEGER DEFAULT 0"),
            ("airing", "INTEGER DEFAULT 1"),
            ("mal_id", "INTEGER"),
            ("schedule_weekday", "INTEGER"),
            ("schedule_time", "TEXT"),
            ("schedule_timezone", "TEXT"),
            ("schedule_source", "TEXT"),
            ("last_schedule_notified_at", "TEXT"),
            ("schedule_checked", "INTEGER DEFAULT 0"),
            ("schedule_checked_at", "TEXT"),
        ):
            try:
                await self._db.execute(
                    f"ALTER TABLE subscriptions ADD COLUMN {column} {definition}"
                )
            except Exception:
                pass
        try:
            await self._db.execute(
                "ALTER TABLE interviews ADD COLUMN episode_start INTEGER"
            )
        except Exception:
            pass
        await self._db.execute(
            "UPDATE interviews SET episode_start = episode WHERE episode_start IS NULL"
        )
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
            """INSERT INTO subscriptions
               (subject_id, subject_name, subject_name_cn, total_eps, status, watched_eps, airing)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(subject_id) DO UPDATE SET
               subject_name = excluded.subject_name,
               subject_name_cn = excluded.subject_name_cn,
               total_eps = excluded.total_eps,
               status = excluded.status,
               watched_eps = excluded.watched_eps,
               airing = excluded.airing""",
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

    @staticmethod
    def _subscription_from_row(r: aiosqlite.Row) -> Subscription:
        """从具名 Row 构造对象，避免升级后列顺序变化造成字段错位。"""
        return Subscription(
            id=r["id"], subject_id=r["subject_id"], subject_name=r["subject_name"],
            subject_name_cn=r["subject_name_cn"] or "", status=r["status"],
            total_eps=r["total_eps"] or 0, last_notified_ep=r["last_notified_ep"] or 0,
            watched_eps=r["watched_eps"] or 0,
            airing=r["airing"] if r["airing"] is not None else 1,
            mal_id=r["mal_id"], schedule_weekday=r["schedule_weekday"],
            schedule_time=r["schedule_time"] or "",
            schedule_timezone=r["schedule_timezone"] or "",
            schedule_source=r["schedule_source"] or "",
            last_schedule_notified_at=r["last_schedule_notified_at"] or "",
            schedule_checked=bool(r["schedule_checked"] or 0),
            schedule_checked_at=r["schedule_checked_at"] or "",
            created_at=r["created_at"],
        )

    async def get_subscription(self, subject_id: int) -> Optional[Subscription]:
        row = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE subject_id = ?",
            (subject_id,),
        )
        if row:
            return self._subscription_from_row(row[0])
        return None

    async def list_subscriptions(self) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions ORDER BY created_at DESC",
        )
        return [self._subscription_from_row(r) for r in rows]

    async def get_active_subscriptions(self) -> list[Subscription]:
        """旧接口，保留给可能的外部调用；更新提醒请使用排期接口。"""
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM subscriptions WHERE status = 3 AND airing = 1"
        )
        return [self._subscription_from_row(r) for r in rows]

    async def get_active_scheduled_subscriptions(self) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            """SELECT * FROM subscriptions
               WHERE status = 3
                 AND schedule_weekday BETWEEN 0 AND 6
                 AND schedule_time IS NOT NULL AND schedule_time != ''"""
        )
        return [self._subscription_from_row(r) for r in rows]

    async def get_subscriptions_needing_schedule_resolution(self) -> list[Subscription]:
        rows = await self.conn.execute_fetchall(
            """SELECT * FROM subscriptions
               WHERE COALESCE(schedule_checked, 0) = 0
                 AND COALESCE(schedule_source, '') != 'manual'"""
        )
        return [self._subscription_from_row(r) for r in rows]

    async def get_subscriptions_for_auto_schedule_refresh(self) -> list[Subscription]:
        """返回可由 Tenrai 刷新的条目，明确排除用户手动设置或关闭的条目。"""
        rows = await self.conn.execute_fetchall(
            """SELECT * FROM subscriptions
               WHERE COALESCE(schedule_source, '') != 'manual'"""
        )
        return [self._subscription_from_row(r) for r in rows]

    async def set_schedule(
        self, subject_id: int, *, weekday: int | None, time: str | None,
        source: str | None, mal_id: int | None = None,
        last_notified_at: str | None = None, checked: bool = True,
    ):
        await self.conn.execute(
            """UPDATE subscriptions SET mal_id = ?, schedule_weekday = ?, schedule_time = ?,
               schedule_timezone = ?, schedule_source = ?, last_schedule_notified_at = ?,
               schedule_checked = ?, schedule_checked_at = CURRENT_TIMESTAMP
               WHERE subject_id = ?""",
            (mal_id, weekday, time, "Asia/Shanghai" if weekday is not None and time else None,
             source, last_notified_at, int(checked), subject_id),
        )
        await self.conn.commit()

    async def record_schedule_check(self, subject_id: int):
        await self.conn.execute(
            """UPDATE subscriptions SET schedule_checked = 1,
               schedule_checked_at = CURRENT_TIMESTAMP WHERE subject_id = ?""",
            (subject_id,),
        )
        await self.conn.commit()

    async def update_last_schedule_notified(self, subject_id: int, notified_at: str):
        await self.conn.execute(
            "UPDATE subscriptions SET last_schedule_notified_at = ? WHERE subject_id = ?",
            (notified_at, subject_id),
        )
        await self.conn.commit()

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
                             question: str, answer: str = "", round_num: int = 1,
                             episode_start: int | None = None) -> Interview:
        episode_start = episode if episode_start is None else episode_start
        cursor = await self.conn.execute(
            """INSERT INTO interviews
               (subject_id, episode, episode_start, question, answer, round)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (subject_id, episode, episode_start, question, answer, round_num),
        )
        await self.conn.commit()
        return Interview(id=cursor.lastrowid, subject_id=subject_id,
                         episode=episode, episode_start=episode_start,
                         question=question, answer=answer, round=round_num)

    async def get_interviews(self, subject_id: int, episode: int) -> list[Interview]:
        rows = await self.conn.execute_fetchall(
            "SELECT * FROM interviews WHERE subject_id = ? AND episode = ? ORDER BY round",
            (subject_id, episode),
        )
        return [Interview(id=r[0], subject_id=r[1], episode=r[2],
                          question=r[3], answer=r[4], round=r[5], created_at=r[6],
                          episode_start=r[7] or r[2]) for r in rows]

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
