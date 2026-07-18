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
    airing: bool | None = None


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


def main_episode_number_for_airdate(episodes, airdate: str) -> int | None:
    """返回发布日期对应的正片集数，忽略 SP、OP、ED 等非正片章节。"""
    for episode in episodes:
        if getattr(episode, "type", 0) != 0 or getattr(episode, "airdate", "") != airdate:
            continue
        number = getattr(episode, "ep", 0)
        if isinstance(number, bool):
            continue
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def format_update_notifications(updated: list[tuple]) -> str:
    """将已确认集数的提醒格式化为单条 QQ 消息。"""
    lines = ["【番剧预计更新提醒】"]
    weekday_names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    for sub, episode, _marker in updated:
        name = sub.subject_name_cn or sub.subject_name
        lines.append(
            f"《{name}》预计更新第{episode}集（北京时间每周"
            f"{weekday_names[sub.schedule_weekday]} {sub.schedule_time}）"
        )
    return "\n".join(lines)


async def resolve_schedule(
    db, sub: Subscription, config, *, client: TenraiClient | None = None,
) -> ScheduleResolution:
    """按 Bangumi 日文原名严格匹配 Tenrai，刷新排期和 airing 生命周期。

    查询失败或未严格匹配时一律保留原提醒配置，避免暂时的上游数据缺失误关闭
    提醒。
    """
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
        return ScheduleResolution(False, "Tenrai 查询失败，请稍后用 /sub schedule auto 重试或手动设置")
    finally:
        if owned_client:
            await client.close()

    if schedule is None:
        await db.record_schedule_check(sub.subject_id)
        logger.info("Tenrai 未匹配到有效排期（%s，%s）", sub.subject_id, sub.subject_name)
        return ScheduleResolution(False, "未找到日文原名严格匹配且包含有效 airing 信息的 MAL 条目")

    if not schedule.airing:
        # 保留原排期，既能在列表/查看命令中展示，也避免覆盖手动设置；airing=0
        # 会把该条目排除出后续有效排期扫描。
        await db.update_schedule_lifecycle(
            sub.subject_id, mal_id=schedule.mal_id, airing=False,
        )
        logger.info("Tenrai 显示条目已完结，已停用更新提醒（%s）", sub.subject_id)
        return ScheduleResolution(
            True, "Tenrai 显示作品已完结，更新提醒已自动停用", airing=False,
        )

    # 手动设置的时间优先，但同样要接受 Tenrai 的 airing 生命周期检查。
    if sub.schedule_source == "manual" and sub.schedule_weekday is not None and sub.schedule_time:
        await db.update_schedule_lifecycle(
            sub.subject_id, mal_id=schedule.mal_id, airing=True,
        )
        return ScheduleResolution(
            True,
            f"已确认仍在连载；保留手动设置的北京时间每周"
            f"{WEEKDAY_NAMES[sub.schedule_weekday]} {sub.schedule_time}",
            sub.schedule_weekday, sub.schedule_time, airing=True,
        )

    if schedule.weekday is None or not schedule.time:
        # 严格标题与生命周期已确认，但排期字段缺失/异常时不能拿空值覆盖原配置。
        await db.update_schedule_lifecycle(
            sub.subject_id, mal_id=schedule.mal_id, airing=True,
        )
        logger.info("Tenrai 未提供完整排期，保留原提醒配置（%s）", sub.subject_id)
        return ScheduleResolution(
            True, "已确认仍在连载，但 Tenrai 未提供完整排期；已保留原提醒配置", airing=True,
        )

    changed = (
        sub.schedule_weekday != schedule.weekday
        or sub.schedule_time != schedule.time
        or sub.schedule_source != "mal"
    )
    marker = (
        handled_marker_for_new_schedule(schedule.weekday, schedule.time)
        if changed else sub.last_schedule_notified_at
    )
    await db.set_schedule(
        sub.subject_id, weekday=schedule.weekday, time=schedule.time, source="mal",
        mal_id=schedule.mal_id, last_notified_at=marker, airing=1,
    )
    logger.info(
        "Tenrai 排期已保存（%s -> MAL %s）：北京时间每周%s %s",
        sub.subject_id, schedule.mal_id, WEEKDAY_NAMES[schedule.weekday], schedule.time,
    )
    return ScheduleResolution(
        True, f"已从 MAL 获取：北京时间每周{WEEKDAY_NAMES[schedule.weekday]} {schedule.time}",
        schedule.weekday, schedule.time, airing=True,
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
    """刷新所有启用提醒的 Tenrai 信息；手动排期仅刷新生命周期。"""
    subs = await db.get_subscriptions_for_auto_schedule_refresh()
    if not subs:
        return []
    client = TenraiClient(config)
    try:
        return [await resolve_schedule(db, sub, config, client=client) for sub in subs]
    finally:
        await client.close()
