"""追番管理处理器 — /sub add|list|remove 命令实现。"""

import logging

from ..api.bangumi import BangumiClient, CollectionType, Subject
from ..storage.database import Database

logger = logging.getLogger(__name__)

STATUS_MAP = {1: "想看", 2: "看过", 3: "在看", 4: "搁置", 5: "抛弃"}


class SubscriptionHandler:
    def __init__(self, db: Database, config):
        self._db = db
        self._config = config

    async def _do_add(self, subject: Subject, user_input: str) -> str:
        """写入订阅并保存别名，返回成功消息。"""
        await self._db.add_subscription(
            subject_id=subject.id,
            subject_name=subject.name,
            subject_name_cn=subject.name_cn,
            total_eps=subject.eps,
        )
        if subject.name_cn:
            await self._db.add_alias(subject.id, subject.name_cn)
        if subject.name:
            await self._db.add_alias(subject.id, subject.name)
        await self._db.add_alias(subject.id, str(subject.id))
        await self._db.add_alias(subject.id, user_input)

        name = subject.name_cn or subject.name
        msg = f"已添加追番：{name} [{subject.id}]（{subject.eps}集）"

        if not self._config.bangumi_access_token:
            return msg

        try:
            client = BangumiClient(self._config)
            collection = await client.get_collection(subject.id)
            if collection is None:
                await client.add_collection(subject.id, CollectionType.DOING)
            await client.close()
        except Exception as e:
            logger.warning(f"同步 Bangumi 收藏失败 (subject_id={subject.id}): {e}")

        return msg

    async def add_subscription(self, subject_id: int) -> str:
        try:
            client = BangumiClient(self._config)
            subject = await client.get_subject(subject_id)
            await client.close()
        except Exception as e:
            logger.error(f"获取番剧信息失败: {e}")
            return f"获取番剧信息失败：{e}"

        return await self._do_add(subject, str(subject_id))

    async def add_by_name(self, name: str) -> "str | dict":
        """通过番剧名称或 subject_id 添加。返回 str 为终端结果，返回 dict 表示需要 LLM 协助确认。"""
        # 如果输入是纯数字，当作 subject_id 直接添加
        if name.isdigit():
            return await self.add_subscription(int(name))

        client = BangumiClient(self._config)
        try:
            results = await client.search_subject(name)
        except Exception as e:
            logger.error(f"搜索番剧失败: {e}")
            return f"搜索番剧失败：{e}"
        finally:
            await client.close()

        if not results:
            return f"未找到与「{name}」相关的番剧，请使用更准确的名称重试。"

        # 检查精确匹配
        for sub in results:
            if sub.name_cn == name or sub.name == name:
                return await self._do_add(sub, name)

        # 无精确匹配，返回搜索结果供 LLM 处理
        search_lines = []
        for i, sub in enumerate(results):
            display_name = sub.name_cn or sub.name
            eps = f"{sub.eps}集" if sub.eps else "集数未知"
            search_lines.append(f"{i + 1}. [{sub.id}] {display_name} ({eps})")

        return {
            "options": results,
            "search_text": "\n".join(search_lines),
        }

    async def confirm_add(self, subject: Subject, user_input: str) -> str:
        """用户确认后执行添加。"""
        return await self._do_add(subject, user_input)

    async def list_subscriptions(self) -> str:
        subs = await self._db.list_subscriptions()
        if not subs:
            return "追番列表为空。使用 /sub add <id | 番剧名称> 添加追番。"
        lines = ["当前追番列表："]
        for sub in subs:
            name = sub.subject_name_cn or sub.subject_name
            status = STATUS_MAP.get(sub.status, "未知")
            watched = sub.watched_eps
            released = sub.last_notified_ep
            if released > 0:
                eps = f"{watched}/{released}"
            else:
                eps = str(watched)
            # 连载中标记
            airing = ""
            if sub.total_eps and released < sub.total_eps:
                airing = " 🔄"
            lines.append(f"  [{sub.subject_id}] {name}{airing} — {status} ({eps})")
        return "\n".join(lines)

    async def remove_subscription(self, subject_id: int) -> str:
        sub = await self._db.get_subscription(subject_id)
        if not sub:
            return f"未找到 subject_id={subject_id} 的追番记录。"
        name = sub.subject_name_cn or sub.subject_name
        await self._db.remove_subscription(subject_id)
        return f"已移除追番：{name} [{subject_id}]"
