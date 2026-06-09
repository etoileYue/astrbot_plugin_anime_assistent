"""定时调度器 — 检查番剧更新并发送通知。"""

import asyncio
import logging
from datetime import datetime, timezone

from astrbot.api.event import MessageChain

logger = logging.getLogger(__name__)


class UpdateScheduler:
    def __init__(self, plugin):
        self._plugin = plugin
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

        db = self._plugin.db
        subs = await db.get_active_subscriptions()
        if not subs:
            return

        client = BangumiClient(self._plugin.plugin_config)
        updated = []

        for sub in subs:
            if not isinstance(sub.subject_id, int) or sub.subject_id <= 0:
                logger.warning(f"跳过 {sub.subject_name}: subject_id 无效 ({sub.subject_id!r})")
                continue
            try:
                episodes = await client.get_episodes(sub.subject_id)
            except Exception as e:
                logger.error(f"获取 {sub.subject_name} 集数失败: {e}")
                continue

            if not episodes:
                continue

            latest_ep = max(ep.ep for ep in episodes if ep.ep > 0)
            if latest_ep > sub.last_notified_ep:
                await db.update_last_notified_ep(sub.id, latest_ep)
                updated.append((sub, latest_ep))

        await client.close()

        if updated and self._umo:
            await self._send_notifications(updated)

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
