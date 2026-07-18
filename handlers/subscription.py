"""追番管理处理器 — /sub add|list|remove 命令实现。"""

import asyncio
import logging

from ..api.bangumi import BangumiClient, CollectionType, Subject, select_cover_url
from ..core.schedule import WEEKDAY_NAMES, resolve_schedule
from ..storage.database import Database
from ..storage.models import Subscription

logger = logging.getLogger(__name__)

STATUS_MAP = {1: "想看", 2: "看过", 3: "在看", 4: "搁置", 5: "抛弃"}


class SubscriptionHandler:
    def __init__(self, db: Database, config):
        self._db = db
        self._config = config

    async def _do_add(self, subject: Subject, user_input: str) -> str:
        """写入订阅并保存别名，返回成功消息。"""
        existing = await self._db.get_subscription(subject.id)
        await self._db.add_subscription(
            subject_id=subject.id,
            subject_name=subject.name,
            subject_name_cn=subject.name_cn,
            total_eps=subject.eps,
            cover_url=select_cover_url(subject.images),
        )
        if subject.name_cn:
            await self._db.add_alias(subject.id, subject.name_cn)
        if subject.name:
            await self._db.add_alias(subject.id, subject.name)
        await self._db.add_alias(subject.id, str(subject.id))
        await self._db.add_alias(subject.id, user_input)

        name = subject.name_cn or subject.name
        msg = f"已添加追番：{name} [{subject.id}]（{subject.eps}集）"

        if self._config.bangumi_access_token:
            client = BangumiClient(self._config)
            try:
                collection = await client.get_collection(subject.id)
                if collection is None:
                    await client.add_collection(subject.id, CollectionType.DOING)
            except Exception as e:
                logger.warning(f"同步 Bangumi 收藏失败 (subject_id={subject.id}): {e}")
            finally:
                await client.close()

        # 添加成功不依赖排期查询；失败时明确提示用户可用北京时间手动覆盖。
        sub = await self._db.get_subscription(subject.id)
        # 重复添加不可覆盖既有手动排期；仅为新条目或升级遗留的未查询条目补齐。
        if sub and not sub.schedule_checked and sub.schedule_source != "manual":
            result = await resolve_schedule(self._db, sub, self._config)
            if result.found:
                msg += f"\n{result.message}。"
            else:
                msg += f"\n自动排期未设置：{result.message}。可用 /sub schedule <番剧标识> <周一-周日> <HH:MM> 手动设置（北京时间）。"
        elif existing and existing.schedule_weekday is not None and existing.schedule_time:
            msg += "\n已保留原有的北京时间排期设置。"

        return msg

    async def add_subscription(self, subject_id: int) -> str:
        client = BangumiClient(self._config)
        try:
            subject = await client.get_subject(subject_id)
        except Exception as e:
            logger.error(f"获取番剧信息失败: {e}")
            return f"获取番剧信息失败：{e}"
        finally:
            await client.close()

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

    async def get_subscription_items(self) -> list[Subscription]:
        """返回保持数据库排序的结构化列表，并补齐旧记录的封面 URL。"""
        subs = await self._db.list_subscriptions()
        missing = [sub for sub in subs if not sub.cover_url]
        if not missing:
            return subs

        client = BangumiClient(self._config)
        semaphore = asyncio.Semaphore(4)

        async def fetch_cover(sub: Subscription) -> tuple[Subscription, str | None]:
            try:
                async with semaphore:
                    subject = await client.get_subject(sub.subject_id)
                return sub, select_cover_url(subject.images)
            except Exception as e:
                logger.warning(
                    "补齐追番封面失败 (subject_id=%s): %s: %s",
                    sub.subject_id,
                    e.__class__.__name__,
                    e,
                )
                return sub, None

        try:
            results = await asyncio.gather(*(fetch_cover(sub) for sub in missing))
            for sub, cover_url in results:
                if cover_url:
                    await self._db.update_cover_url(sub.subject_id, cover_url)
                    sub.cover_url = cover_url
        finally:
            await client.close()
        return subs

    @staticmethod
    def format_subscriptions_text(subs: list[Subscription]) -> str:
        """生成完整纯文本列表，供常规接口与图片失败降级共享。"""
        if not subs:
            return "追番列表为空。使用 /sub add <id | 番剧名称> 添加追番。"
        lines = ["当前追番列表："]
        for sub in subs:
            name = sub.subject_name_cn or sub.subject_name
            status = STATUS_MAP.get(sub.status, "未知")
            watched = sub.watched_eps
            eps = f"{watched}/{sub.total_eps}" if sub.total_eps else str(watched)
            marker = "🔄 " if sub.airing else ""
            if sub.airing and sub.schedule_weekday is not None and sub.schedule_time:
                schedule = f"；每周{WEEKDAY_NAMES[sub.schedule_weekday]} {sub.schedule_time}"
            elif sub.airing and sub.schedule_source == "manual":
                schedule = "；更新提醒已关闭"
            elif sub.airing and sub.schedule_checked:
                schedule = "；未获取到自动排期"
            elif sub.airing:
                schedule = "；排期查询中"
            else:
                schedule = ""
            lines.append(f"  {marker}[{sub.subject_id}] {name} — {status} ({eps}){schedule}")
        return "\n".join(lines)

    async def list_subscriptions(self) -> str:
        """兼容原有调用：补齐数据后返回纯文本列表。"""
        return self.format_subscriptions_text(await self.get_subscription_items())

    async def remove_subscription(self, subject_id: int) -> str:
        sub = await self._db.get_subscription(subject_id)
        if not sub:
            return f"未找到 subject_id={subject_id} 的追番记录。"
        name = sub.subject_name_cn or sub.subject_name
        await self._db.remove_subscription(subject_id)
        return f"已移除追番：{name} [{subject_id}]"
