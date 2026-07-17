"""北京时间排期的解析、校验与存储辅助。"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..api.tenrai import TenraiClient
from ..storage.models import Subscription

logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
WEEKDAY_INPUTS = {name: index for index, name in enumerate(WEEKDAY_NAMES)}


@dataclass(frozen=True)
class ScheduleResolution:
    found: bool
    message: str
    weekday: int | None = None
    time: str | None = None


def valid_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return len(value) == 5
    except ValueError:
        return False


def occurrence_this_week(weekday: int, clock: str, now: datetime | None = None) -> datetime:
    """返回给定时区 now 所在周的播出时间。"""
    now = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    hour, minute = map(int, clock.split(":"))
    date = now.date() + timedelta(days=weekday - now.weekday())
    return datetime(date.year, date.month, date.day, hour, minute, tzinfo=SHANGHAI)


def handled_marker_for_new_schedule(weekday: int, clock: str, now: datetime | None = None) -> str | None:
    """若本周播出时刻已过，写入标记，避免刚设置就补发旧通知。"""
    now = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    occurrence = occurrence_this_week(weekday, clock, now)
    return occurrence.isoformat() if occurrence <= now else None


async def resolve_schedule(
    db, sub: Subscription, config, *, client: TenraiClient | None = None,
    clear_on_failure: bool = False,
) -> ScheduleResolution:
    """按 Bangumi 日文原名严格匹配 Tenrai，并保存为北京时间排期。"""
    if not sub.subject_name.strip():
        await db.record_schedule_check(sub.subject_id)
        logger.info("跳过 Tenrai 排期查询（%s）：Bangumi 日文原名为空", sub.subject_id)
        return ScheduleResolution(False, "Bangumi 日文原名为空，无法自动获取排期")

    owned_client = client is None
    client = client or TenraiClient(config)
    try:
        schedule = await client.find_exact_broadcast(sub.subject_name)
    except Exception as exc:
        logger.warning("Tenrai 排期查询失败（%s）：%s", sub.subject_id, exc)
        await db.record_schedule_check(sub.subject_id)
        if clear_on_failure:
            await db.set_schedule(sub.subject_id, weekday=None, time=None, source=None)
        return ScheduleResolution(False, "Tenrai 查询失败，请稍后用 /sub schedule auto 重试或手动设置")
    finally:
        if owned_client:
            await client.close()

    if schedule is None:
        await db.record_schedule_check(sub.subject_id)
        if clear_on_failure:
            await db.set_schedule(sub.subject_id, weekday=None, time=None, source=None)
        logger.info("Tenrai 未匹配到有效排期（%s，%s）", sub.subject_id, sub.subject_name)
        return ScheduleResolution(False, "未找到日文原名严格匹配且具有完整播出时间的 MAL 条目")

    marker = handled_marker_for_new_schedule(schedule.weekday, schedule.time)
    await db.set_schedule(
        sub.subject_id, weekday=schedule.weekday, time=schedule.time, source="mal",
        mal_id=schedule.mal_id, last_notified_at=marker,
    )
    logger.info(
        "Tenrai 排期已保存（%s -> MAL %s）：北京时间每周%s %s",
        sub.subject_id, schedule.mal_id, WEEKDAY_NAMES[schedule.weekday], schedule.time,
    )
    return ScheduleResolution(
        True, f"已从 MAL 获取：北京时间每周{WEEKDAY_NAMES[schedule.weekday]} {schedule.time}",
        schedule.weekday, schedule.time,
    )


async def resolve_missing_schedules(db, config) -> list[ScheduleResolution]:
    """升级/同步后的单次补齐；不会触碰手动设置或已查询条目。"""
    pending = await db.get_subscriptions_needing_schedule_resolution()
    if not pending:
        return []
    client = TenraiClient(config)
    try:
        return [await resolve_schedule(db, sub, config, client=client) for sub in pending]
    finally:
        await client.close()


async def refresh_auto_schedules(db, config) -> list[ScheduleResolution]:
    """显式刷新所有自动管理的排期；绝不覆盖手动设置或“已关闭”。"""
    subs = await db.get_subscriptions_for_auto_schedule_refresh()
    if not subs:
        return []
    client = TenraiClient(config)
    try:
        return [await resolve_schedule(db, sub, config, client=client) for sub in subs]
    finally:
        await client.close()
