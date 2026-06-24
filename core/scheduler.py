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
        """注册用于主动推送消息的 unified_msg_origin 并持久化。"""
        self._umo = umo
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_umo(umo))
        except RuntimeError:
            pass

    async def _persist_umo(self, umo: str):
        try:
            await self._plugin.db.set_task_state("last_umo", umo)
        except Exception as e:
            logger.warning(f"持久化 UMO 失败: {e}")

    async def _get_umo(self) -> str | None:
        """获取 UMO，优先内存，其次数据库。"""
        if self._umo:
            return self._umo
        db = self._plugin.db
        stored = await db.get_task_state("last_umo")
        if stored:
            self._umo = stored
            logger.info("从数据库恢复了 UMO")
        return self._umo

    def start(self):
        """启动调度器后台任务，并保存引用以便 terminate 时清理。"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.run())

    async def run(self):
        self._running = True
        interval_hours = self._plugin.plugin_config.check_interval_hours
        logger.info(f"番剧更新调度器已启动，检查间隔: {interval_hours} 小时")
        while self._running:
            try:
                await self._do_check()
            except Exception as e:
                logger.error(f"更新检查失败: {e}")
            logger.info(
                f"下次番剧更新检查将在 {interval_hours} 小时后进行"
            )
            await asyncio.sleep(interval_hours * 3600)

    async def check_once(self):
        await self._do_check()

    async def _do_check(self):
        from ..api.bangumi import BangumiClient
        from ..core.sync import sync_from_bangumi

        db = self._plugin.db

        logger.info("=" * 40)
        logger.info("番剧更新检查开始")

        # Step A: 从 Bangumi 同步「在看」收藏，以 Bangumi 数据覆盖本地
        try:
            total, added, updated, removed, progress_diffs = await sync_from_bangumi(
                db, self._plugin.plugin_config
            )
            logger.info(
                f"[Step A] Bangumi 同步完成: 总计 {total} 条, "
                f"新增 {added}, 更新 {updated}, 移除 {removed}, "
                f"进度变化 {len(progress_diffs)} 条"
            )
        except Exception as e:
            logger.error(f"Bangumi 同步失败: {e}")
            total, added, updated, removed, progress_diffs = 0, 0, 0, 0, []

        # Step B: 对进度领先的条目自动触发访谈
        interview_count = 0
        umo = await self._get_umo()
        if progress_diffs and umo and self._interview_handler:
            for diff in progress_diffs:
                if self._interview_handler.has_active_session(diff["subject_id"], diff["bangumi_eps"]):
                    continue
                try:
                    question = await self._interview_handler.try_start_auto(
                        umo=umo,
                        subject_id=diff["subject_id"],
                        episode=diff["bangumi_eps"],
                        subject_name=diff["subject_name"],
                        subject_name_cn=diff.get("subject_name_cn", ""),
                    )
                    if question:
                        interview_count += 1
                        name = diff.get("subject_name_cn") or diff["subject_name"]
                        msg = (
                            f"检测到你在 Bangumi 上《{name}》的观看进度已更新"
                            f"（第{diff['bangumi_eps']}集）。\n\n"
                            f"{question}\n\n"
                            f"（随时可以说\"不聊了\"结束访谈）"
                        )
                        hint = self._interview_handler.get_routing_hint(
                            exclude=(diff["subject_id"], diff["bangumi_eps"])
                        )
                        if hint:
                            msg += "\n" + hint
                        chain = MessageChain().message(msg)
                        await self._plugin.context.send_message(umo, chain)
                except Exception as e:
                    logger.error(
                        f"自动访谈启动失败 ({diff['subject_name']}): {e}"
                    )
        elif progress_diffs and not umo:
            logger.warning(
                f"检测到 {len(progress_diffs)} 条进度变化，但 UMO 未设置，跳过访谈触发"
            )

        logger.info(f"[Step B] 自动访谈: 触发了 {interview_count} 个会话")

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
                    if sub.total_eps and latest_ep >= sub.total_eps:
                        await db.update_airing(sub.subject_id, 0)
            finally:
                await client.close()

        logger.info(
            f"[Step C] 剧集检查: 扫描了 {len(subs)} 个订阅, "
            f"发现 {len(updated_subs)} 个更新"
        )

        if updated_subs and umo:
            await self._send_notifications(umo, updated_subs)

        # 更新检查时间
        now = datetime.now(timezone.utc).isoformat()
        await db.set_task_state("last_check_time", now)

        logger.info(
            f"番剧更新检查完成 (时间: {now})"
        )
        logger.info("=" * 40)

    async def _send_notifications(self, umo: str, updated: list):
        lines = ["【番剧更新提醒】"]
        for sub, latest_ep in updated:
            name = sub.subject_name_cn or sub.subject_name
            lines.append(f"{name}")
            lines.append(f"第{latest_ep}集已更新")
            lines.append("")
        msg = "\n".join(lines).strip()
        chain = MessageChain().message(msg)
        try:
            await self._plugin.context.send_message(umo, chain)
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

    async def stop(self):
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"调度器后台任务退出时抛出异常: {e}")
        self._task = None
