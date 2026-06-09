"""进度同步处理器 — 解析"番剧名N集看完"类消息。"""

import logging
import re
from dataclasses import dataclass

from ..api.bangumi import BangumiClient, CollectionType
from ..storage.database import Database

logger = logging.getLogger(__name__)

PROGRESS_PATTERNS = [
    re.compile(r"(.+?)(\d{1,4})\s*集?\s*(?:看完|看完了|追完|追完了)"),
    re.compile(r"(.+?)(?:看到|追到)\s*第?\s*(\d{1,4})\s*集"),
    re.compile(r"(.+?)(?:看了|追了)\s*第?\s*(\d{1,4})\s*集"),
]


@dataclass
class SyncResult:
    message: str
    subject_id: int = 0
    episode: int = 0
    subject_name: str = ""
    subject_name_cn: str = ""


class ProgressHandler:
    def __init__(self, db: Database, config):
        self._db = db
        self._config = config

    async def try_sync(self, event) -> SyncResult | None:
        text = event.message_str.strip()
        if not text:
            return None

        match = None
        for pattern in PROGRESS_PATTERNS:
            match = pattern.search(text)
            if match:
                break
        if not match:
            return None

        alias = match.group(1).strip()
        episode = int(match.group(2))

        alias_row = await self._db.find_by_alias(alias)
        if not alias_row:
            return None

        subject_id = alias_row.subject_id
        if not isinstance(subject_id, int) or subject_id <= 0:
            logger.warning(f"别名 {alias!r} 的 subject_id 无效 ({subject_id!r})")
            return None

        sub = await self._db.get_subscription(subject_id)
        if not sub:
            try:
                client = BangumiClient(self._config)
                subject = await client.get_subject(subject_id)
                sub = await self._db.add_subscription(
                    subject_id=subject.id,
                    subject_name=subject.name,
                    subject_name_cn=subject.name_cn,
                    total_eps=subject.eps,
                )
                await client.close()
            except Exception as e:
                logger.error(f"自动订阅失败: {e}")
                return SyncResult(message=f"未找到该番剧的追番记录，且自动添加失败：{e}")

        try:
            client = BangumiClient(self._config)
            collection = await client.get_collection(subject_id)
            if collection is None:
                await client.add_collection(subject_id, CollectionType.DOING)
            episodes = await client.get_episodes(subject_id)
            target = None
            for ep in episodes:
                if ep.ep == episode:
                    target = ep
                    break
            if target is None:
                await client.close()
                name = sub.subject_name_cn or sub.subject_name
                return SyncResult(message=f"未找到 {name} 第{episode}集（可能章节数据尚未更新）。")

            await client.mark_episode_watched(target.id)
            await client.close()
        except Exception as e:
            logger.error(f"同步 Bangumi 失败: {e}")
            return SyncResult(message=f"同步 Bangumi 失败：{e}")

        await self._db.log_watch(subject_id, episode, source="manual")
        if episode > sub.last_notified_ep:
            await self._db.update_last_notified_ep(sub.id, episode)

        name = sub.subject_name_cn or sub.subject_name
        eps_display = f"{episode}/{sub.total_eps}" if sub.total_eps else str(episode)
        return SyncResult(
            message=f"【已同步 Bangumi】\n{name}\n观看进度：{eps_display}",
            subject_id=subject_id,
            episode=episode,
            subject_name=sub.subject_name,
            subject_name_cn=sub.subject_name_cn or "",
        )
