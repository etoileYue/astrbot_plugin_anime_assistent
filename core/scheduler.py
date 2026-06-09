"""定时调度器 — 检查番剧更新、同步 Bangumi 进度、触发自动访谈。"""

import asyncio
import logging
from datetime import datetime, timezone

from astrbot.api.event import MessageChain

logger = logging.getLogger(__name__)


class UpdateScheduler:
    def __init__(self, plugin, interview_handler=None):
        self._plugin = plugin
        self._interview_handler = interview_handler
        self._running = False
        self._task = None
        self._umo: str | None = None

    def set_umo(self, umo: str):
        """注册用于主动推送消息的 unified_msg_origin。"""
        self._umo = umo

    async def run(self):
        self._running = True
        while self._running:
            try:
                await self._do_check()
            except Exception as e:
                logger.error(f"更新检查失败: {e}")
            await asyncio.sleep(self._plugin.plugin_config.check_interval_hours * 3600)

    async def check_once(self):
        await self._do_check()

    async def _do_check(self):
        from ..api.bangumi import BangumiClient
        from ..core.sync import sync_from_bangumi

        db = self._plugin.db

        # Step A: 从 Bangumi 同步「在看」收藏，以 Bangumi 数据覆盖本地
        try:
            total, added, updated, removed, progress_diffs = await sync_from_bangumi(
                db, self._plugin.plugin_config
            )
        except Exception as e:
            logger.error(f"Bangumi 同步失败: {e}")
            total, added, updated, removed, progress_diffs = 0, 0, 0, 0, []

        # Step B: 对进度领先的条目自动触发访谈
        if progress_diffs and self._umo and self._interview_handler:
            for diff in progress_diffs:
                try:
                    question = await self._interview_handler.try_start_auto(
                        umo=self._umo,
                        subject_id=diff["subject_id"],
                        episode=diff["bangumi_eps"],
                        subject_name=diff["subject_name"],
                        subject_name_cn=diff.get("subject_name_cn", ""),
                    )
                    if question:
                        name = diff.get("subject_name_cn") or diff["subject_name"]
                        msg = (
                            f"检测到你在 Bangumi 上《{name}》的观看进度已更新"
                            f"（第{diff['bangumi_eps']}集）。\n\n"
                            f"{question}\n\n"
                            f"（随时可以说\"不聊了\"结束访谈）"
                        )
                        chain = MessageChain().message(msg)
                        await self._plugin.context.send_message(self._umo, chain)
                except Exception as e:
                    logger.error(
                        f"自动访谈启动失败 ({diff['subject_name']}): {e}"
                    )

        # Step C: 检查新剧集发布，比对 last_notified_ep 发送通知
        subs = await db.get_active_subscriptions()
        updated_subs = []

        if subs:
            client = BangumiClient(self._plugin.plugin_config)
            try:
                for sub in subs:
                    if not isinstance(sub.subject_id, int) or sub.subject_id <= 0:
                        logger.warning(
                            f"跳过 {sub.subject_name}: subject_id 无效 ({sub.subject_id!r})"
                        )
                        continue
                    try:
                        episodes = await client.get_episodes(sub.subject_id)
                    except Exception as e:
                        logger.error(f"获取 {sub.subject_name} 集数失败: {e}")
                        continue

                    if not episodes:
                        continue

                    released = [
                        ep for ep in episodes
                        if ep.ep > 0 and (ep.name or ep.name_cn)
                    ]
                    if not released:
                        continue
                    latest_ep = max(ep.ep for ep in released)
                    if latest_ep > sub.last_notified_ep:
                        await db.update_last_notified_ep(sub.id, latest_ep)
                        updated_subs.append((sub, latest_ep))
            finally:
                await client.close()

        if updated_subs and self._umo:
            await self._send_notifications(updated_subs)

        # 更新检查时间
        now = datetime.now(timezone.utc).isoformat()
        await db.set_task_state("last_check_time", now)

    async def _send_notifications(self, updated: list):
        lines = ["【番剧更新提醒】"]
        for sub, latest_ep in updated:
            name = sub.subject_name_cn or sub.subject_name
            lines.append(f"{name}")
            lines.append(f"第{latest_ep}集已更新")
            lines.append("")
        msg = "\n".join(lines).strip()
        chain = MessageChain().message(msg)
        try:
            await self._plugin.context.send_message(self._umo, chain)
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
