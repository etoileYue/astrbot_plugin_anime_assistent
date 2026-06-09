"""数据模型定义 — 对应数据库表结构。"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Subscription:
    id: int = 0
    subject_id: int = 0
    subject_name: str = ""
    subject_name_cn: str = ""
    status: int = 3
    total_eps: int = 0
    last_notified_ep: int = 0
    watched_eps: int = 0
    airing: int = 1
    created_at: str = ""


@dataclass
class Alias:
    id: int = 0
    subject_id: int = 0
    alias: str = ""


@dataclass
class WatchLog:
    id: int = 0
    subject_id: int = 0
    episode: int = 0
    watched_at: str = ""
    source: str = "manual"


@dataclass
class Interview:
    id: int = 0
    subject_id: int = 0
    episode: int = 0
    question: str = ""
    answer: Optional[str] = None
    round: int = 1
    created_at: str = ""
