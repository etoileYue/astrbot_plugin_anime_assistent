"""Tenrai 排期、数据库迁移和北京时间提醒辅助函数测试。"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bangumibot.api.bangumi import Episode
from bangumibot.api.tenrai import BroadcastSchedule, TenraiClient
from bangumibot.core.schedule import (
    format_update_notifications,
    handled_marker_for_new_schedule,
    main_episode_number_for_airdate,
    occurrence_this_week,
    resolve_schedule,
)
from bangumibot.storage.models import Subscription
from bangumibot.storage.database import Database


def test_tenrai_conversion_changes_weekday_when_timezone_crosses_day():
    # 东京周一 00:30 是北京时间周日 23:30。
    result = TenraiClient._to_shanghai({
        "mal_id": 42,
        "airing": True,
        "broadcast": {"day": "Mondays", "time": "00:30", "timezone": "Asia/Tokyo"},
    })
    assert result is not None
    assert (result.weekday, result.time) == (6, "23:30")


def test_tenrai_completed_exact_result_keeps_lifecycle_without_broadcast():
    result = TenraiClient._to_shanghai({"mal_id": 42, "airing": False})
    assert result == BroadcastSchedule(mal_id=42, airing=False)


@pytest.mark.asyncio
async def test_tenrai_only_accepts_normalized_exact_japanese_title():
    client = object.__new__(TenraiClient)

    async def fake_search(_title):
        return [
            {"mal_id": 1, "airing": True, "title_japanese": "葬送のフリーレン", "broadcast": {
                "day": "Fridays", "time": "23:00", "timezone": "Asia/Tokyo",
            }},
            {"mal_id": 2, "airing": True, "title_japanese": "葬送のフリーレン　", "broadcast": {
                "day": "Saturdays", "time": "23:00", "timezone": "Asia/Tokyo",
            }},
        ]

    client._search = fake_search
    result = await client.find_exact_broadcast("葬送のフリーレン")
    assert result is not None
    assert result.mal_id == 1

    # 只有相近标题时不得误关联。
    async def only_similar(_title):
        return [{"mal_id": 3, "airing": True, "title_japanese": "葬送のフリーレン 2", "broadcast": {
            "day": "Fridays", "time": "23:00", "timezone": "Asia/Tokyo",
        }}]

    client._search = only_similar
    assert await client.find_exact_broadcast("葬送のフリーレン") is None


@pytest.mark.asyncio
async def test_tenrai_exact_match_ignores_all_unicode_whitespace():
    client = object.__new__(TenraiClient)

    async def fake_search(_title):
        return [{
            "mal_id": 42,
            "airing": True,
            "title_japanese": "機動戦士　ガンダム\t水星の\n魔女",
            "broadcast": {
                "day": "Sundays", "time": "17:00", "timezone": "Asia/Tokyo",
            },
        }]

    client._search = fake_search
    result = await client.find_exact_broadcast("機動戦士ガンダム 水星の魔女")

    assert result is not None
    assert result.mal_id == 42


@pytest.mark.asyncio
async def test_tenrai_title_comparison_remains_strict_after_removing_whitespace():
    client = object.__new__(TenraiClient)

    async def fake_search(_title):
        return [{
            "mal_id": 43,
            "airing": True,
            "title_japanese": "機動戦士 ガンダム 水星の魔女 Season 2",
            "broadcast": {
                "day": "Sundays", "time": "17:00", "timezone": "Asia/Tokyo",
            },
        }]

    client._search = fake_search
    assert await client.find_exact_broadcast("機動戦士ガンダム水星の魔女") is None


@pytest.mark.asyncio
async def test_database_schedule_migration_and_manual_schedule(tmp_path):
    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Test")
    await db.set_schedule(1, weekday=0, time="20:00", source="manual", mal_id=99)

    sub = await db.get_subscription(1)
    assert sub is not None
    assert (sub.mal_id, sub.schedule_weekday, sub.schedule_time) == (99, 0, "20:00")
    assert sub.schedule_timezone == "Asia/Shanghai"
    assert sub.schedule_source == "manual"
    assert await db.get_subscriptions_needing_schedule_resolution() == []
    # 启用的手动排期也要查询 airing，但不能由查询改写星期和时间。
    assert [sub.subject_id for sub in await db.get_subscriptions_for_auto_schedule_refresh()] == [1]
    await db.close()


def test_past_schedule_is_marked_and_future_schedule_is_not():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))  # Monday
    assert handled_marker_for_new_schedule(0, "11:00", now)
    assert handled_marker_for_new_schedule(0, "13:00", now) is None
    occurrence = occurrence_this_week(6, "20:00", now)
    assert occurrence.weekday() == 6
    assert occurrence.strftime("%H:%M") == "20:00"


class FakeTenraiClient:
    def __init__(self, result):
        self.result = result

    async def find_exact_broadcast(self, _title):
        return self.result


@pytest.mark.asyncio
async def test_tenrai_airing_false_disables_auto_and_manual_reminders(tmp_path):
    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Auto")
    await db.add_subscription(2, "Manual")
    await db.set_schedule(1, weekday=0, time="20:00", source="mal", mal_id=10, airing=1)
    await db.set_schedule(2, weekday=2, time="21:30", source="manual", mal_id=20, airing=1)
    stopped = FakeTenraiClient(BroadcastSchedule(mal_id=99, airing=False))

    auto = await db.get_subscription(1)
    manual = await db.get_subscription(2)
    assert auto is not None and manual is not None
    assert (await resolve_schedule(db, auto, None, client=stopped)).found
    assert (await resolve_schedule(db, manual, None, client=stopped)).found

    auto = await db.get_subscription(1)
    manual = await db.get_subscription(2)
    assert auto is not None and manual is not None
    assert auto.airing == 0
    assert manual.airing == 0
    assert (manual.schedule_weekday, manual.schedule_time, manual.schedule_source) == (2, "21:30", "manual")
    assert await db.get_active_scheduled_subscriptions() == []
    await db.close()


@pytest.mark.asyncio
async def test_airing_true_preserves_manual_schedule_and_failures_preserve_config(tmp_path):
    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Manual")
    await db.set_schedule(1, weekday=4, time="19:15", source="manual", mal_id=10, airing=1)
    sub = await db.get_subscription(1)
    assert sub is not None

    running = FakeTenraiClient(BroadcastSchedule(mal_id=11, airing=True, weekday=0, time="00:00"))
    result = await resolve_schedule(db, sub, None, client=running)
    assert result.found
    refreshed = await db.get_subscription(1)
    assert refreshed is not None
    assert (refreshed.schedule_weekday, refreshed.schedule_time, refreshed.schedule_source) == (4, "19:15", "manual")
    assert (refreshed.mal_id, refreshed.airing) == (11, 1)

    unmatched = FakeTenraiClient(None)
    result = await resolve_schedule(db, refreshed, None, client=unmatched)
    assert not result.found
    unchanged = await db.get_subscription(1)
    assert unchanged is not None
    assert (unchanged.schedule_weekday, unchanged.schedule_time, unchanged.airing) == (4, "19:15", 1)
    await db.close()


def test_main_episode_number_uses_airdate_and_excludes_specials():
    now = datetime(2026, 7, 13, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    occurrence = occurrence_this_week(0, "20:00", now)
    assert occurrence <= now
    episodes = [
        Episode(1, 0, "SP", "", "2026-07-13", type=1),
        Episode(2, 7, "", "", "2026-07-13", type=0),
        Episode(3, 8, "", "", "2026-07-20", type=0),
    ]
    assert main_episode_number_for_airdate(episodes, "2026-07-13") == 7
    assert main_episode_number_for_airdate(episodes, occurrence.date().isoformat()) == 7
    assert main_episode_number_for_airdate(episodes, "2026-07-14") is None

    sub = Subscription(
        subject_name="原名", subject_name_cn="中文名", schedule_weekday=0, schedule_time="20:00",
    )
    assert format_update_notifications([(sub, 7, "marker")]) == (
        "【番剧预计更新提醒】\n"
        "《中文名》预计更新第7集（北京时间每周周一 20:00）"
    )
