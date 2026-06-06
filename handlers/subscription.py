"""追番管理处理器 — /sub add|list|remove 命令实现。"""

import logging

from ..api.bangumi import BangumiClient
from ..storage.database import Database

logger = logging.getLogger(__name__)

STATUS_MAP = {1: "想看", 2: "看过", 3: "在看", 4: "搁置", 5: "抛弃"}


class SubscriptionHandler:
    def __init__(self, db: Database, config):
        self._db = db
        self._config = config

    async def add_subscription(self, event, subject_id: int) -> str:
        try:
            client = BangumiClient(self._config)
            subject = await client.get_subject(subject_id)
        except Exception as e:
            logger.error(f"获取番剧信息失败: {e}")
            return f"获取番剧信息失败：{e}"

        qq_id = event.get_sender_id()
        user = await self._db.ensure_user(qq_id)
        await self._db.add_subscription(
            user_id=user.id,
            subject_id=subject.id,
            subject_name=subject.name,
            subject_name_cn=subject.name_cn,
            total_eps=subject.eps,
        )
        # 自动添加别名
        if subject.name_cn:
            await self._db.add_alias(subject.id, subject.name_cn)
        if subject.name:
            await self._db.add_alias(subject.id, subject.name)
        await self._db.add_alias(subject.id, str(subject.id))

        await client.close()
        name = subject.name_cn or subject.name
        return f"已添加追番：{name} [{subject.id}]（{subject.eps}集）"

    async def list_subscriptions(self, event) -> str:
        qq_id = event.get_sender_id()
        user = await self._db.ensure_user(qq_id)
        subs = await self._db.list_subscriptions(user.id)
        if not subs:
            return "追番列表为空。使用 /sub add <id> 添加追番。"
        lines = ["当前追番列表："]
        for sub in subs:
            name = sub.subject_name_cn or sub.subject_name
            status = STATUS_MAP.get(sub.status, "未知")
            eps = f"{sub.last_notified_ep}/{sub.total_eps}" if sub.total_eps else str(sub.last_notified_ep)
            lines.append(f"  [{sub.subject_id}] {name} — {status} ({eps})")
        return "\n".join(lines)

    async def remove_subscription(self, event, subject_id: int) -> str:
        qq_id = event.get_sender_id()
        user = await self._db.ensure_user(qq_id)
        sub = await self._db.get_subscription(user.id, subject_id)
        if not sub:
            return f"未找到 subject_id={subject_id} 的追番记录。"
        name = sub.subject_name_cn or sub.subject_name
        await self._db.remove_subscription(user.id, subject_id)
        return f"已移除追番：{name} [{subject_id}]"
