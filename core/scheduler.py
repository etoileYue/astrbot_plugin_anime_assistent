"""定时调度器 — 检查番剧更新、同步 Bangumi 进度、触发自动访谈。"""

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from astrbot.api.event import MessageChain

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


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

    async def check_once(self, refresh_schedules: bool = False):
        """执行一轮检查；仅用户显式 /sync 时刷新全部自动排期。"""
        return await self._do_check(refresh_schedules=refresh_schedules)

    async def _do_check(self, refresh_schedules: bool = False):
        from ..core.schedule import (
            occurrence_this_week,
            refresh_auto_schedules,
            resolve_missing_schedules,
        )
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
            logger.error(
                f"Bangumi 同步失败: {e.__class__.__name__}: {e}"
            )
            total, added, updated, removed, progress_diffs = 0, 0, 0, 0, []

        # 新增的云端收藏和升级后的存量记录只会在这里补齐一次；手动排期不受影响。
        try:
            if refresh_schedules:
                resolved = await refresh_auto_schedules(db, self._plugin.plugin_config)
            else:
                resolved = await resolve_missing_schedules(db, self._plugin.plugin_config)
            if resolved:
                success = sum(result.found for result in resolved)
                logger.info("[排期] 已查询 %s 条，成功 %s 条", len(resolved), success)
        except Exception as e:
            logger.warning("补齐 Tenrai 排期失败（不影响本轮检查）：%s", e)

        # Step B: 对进度领先的条目自动触发访谈
        interview_count = 0
        umo = await self._get_umo()
        if progress_diffs and umo and self._interview_handler:
            for diff in progress_diffs:
                start_episode = diff["start_episode"]
                end_episode = diff["end_episode"]
                if self._interview_handler.has_active_session(
                    diff["subject_id"], start_episode, end_episode
                ):
                    continue
                try:
                    question = await self._interview_handler.try_start_auto(
                        umo=umo,
                        subject_id=diff["subject_id"],
                        episode=end_episode,
                        subject_name=diff["subject_name"],
                        subject_name_cn=diff.get("subject_name_cn", ""),
                        start_episode=start_episode,
                    )
                    if question:
                        interview_count += 1
                        name = diff.get("subject_name_cn") or diff["subject_name"]
                        episode_label = (
                            f"第{end_episode}集"
                            if start_episode == end_episode
                            else f"第{start_episode}-{end_episode}集"
                        )
                        msg = (
                            f"检测到你在 Bangumi 上《{name}》的观看进度已更新"
                            f"（{episode_label}）。\n\n"
                            f"{question}\n\n"
                            f"（随时可以说\"不聊了\"结束访谈）"
                        )
                        hint = self._interview_handler.get_routing_hint(
                            exclude=(diff["subject_id"], start_episode, end_episode)
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

        # Step C: 只按北京时间的播出排期提醒，不再查询 Bangumi 分集。
        subs = await db.get_active_scheduled_subscriptions()
        updated_subs = []
        now = datetime.now(SHANGHAI)
        last_check = await self._last_check_in_shanghai(db)
        interval = max(float(self._plugin.plugin_config.check_interval_hours), 0.01)
        # 超过两个调度周期视为停机恢复，不补发已经错过的排期。
        continuous = last_check is not None and (now - last_check).total_seconds() <= interval * 7200

        if continuous:
            for sub in subs:
                try:
                    occurrence = occurrence_this_week(sub.schedule_weekday, sub.schedule_time, now)
                except (TypeError, ValueError):
                    logger.warning("跳过无效排期：%s", sub.subject_name)
                    continue
                marker = occurrence.isoformat()
                if last_check <= occurrence <= now and sub.last_schedule_notified_at != marker:
                    await db.update_last_schedule_notified(sub.subject_id, marker)
                    updated_subs.append(sub)

        logger.info(
            f"[Step C] 排期检查: 扫描了 {len(subs)} 个有效排期, "
            f"触发 {len(updated_subs)} 条提醒"
        )

        if updated_subs and umo:
            await self._send_notifications(umo, updated_subs)

        # 更新检查时间
        now_utc = now.astimezone(timezone.utc).isoformat()
        await db.set_task_state("last_check_time", now_utc)

        logger.info(
            f"番剧更新检查完成 (时间: {now_utc})"
        )
        logger.info("=" * 40)
        return resolved if 'resolved' in locals() else []

    async def _last_check_in_shanghai(self, db) -> datetime | None:
        value = await db.get_task_state("last_check_time")
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(SHANGHAI)
        except ValueError:
            logger.warning("忽略无法解析的 last_check_time：%r", value)
            return None

    async def _send_notifications(self, umo: str, updated: list):
        lines = ["【番剧预计更新提醒】"]
        weekday_names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
        for sub in updated:
            name = sub.subject_name_cn or sub.subject_name
            lines.append(f"{name}")
            lines.append(
                f"预计更新（北京时间每周{weekday_names[sub.schedule_weekday]} {sub.schedule_time}）"
            )
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
