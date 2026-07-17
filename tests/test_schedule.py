"""Tenrai 排期、数据库迁移和北京时间提醒辅助函数测试。"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bangumibot.api.tenrai import TenraiClient
from bangumibot.core.schedule import (
    handled_marker_for_new_schedule,
    occurrence_this_week,
)
from bangumibot.storage.database import Database


def test_tenrai_conversion_changes_weekday_when_timezone_crosses_day():
    # 东京周一 00:30 是北京时间周日 23:30。
    result = TenraiClient._to_shanghai({
        "mal_id": 42,
        "broadcast": {"day": "Mondays", "time": "00:30", "timezone": "Asia/Tokyo"},
    })
    assert result is not None
    assert (result.weekday, result.time) == (6, "23:30")


@pytest.mark.asyncio
async def test_tenrai_only_accepts_normalized_exact_japanese_title():
    client = object.__new__(TenraiClient)

    async def fake_search(_title):
        return [
            {"mal_id": 1, "title_japanese": "葬送のフリーレン", "broadcast": {
                "day": "Fridays", "time": "23:00", "timezone": "Asia/Tokyo",
            }},
            {"mal_id": 2, "title_japanese": "葬送のフリーレン　", "broadcast": {
                "day": "Saturdays", "time": "23:00", "timezone": "Asia/Tokyo",
            }},
        ]

    client._search = fake_search
    result = await client.find_exact_broadcast("葬送のフリーレン")
    assert result is not None
    assert result.mal_id == 1

    # 只有相近标题时不得误关联。
    async def only_similar(_title):
        return [{"mal_id": 3, "title_japanese": "葬送のフリーレン 2", "broadcast": {
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
    # 显式刷新也不得触碰手动设置。
    assert await db.get_subscriptions_for_auto_schedule_refresh() == []
    await db.close()


def test_past_schedule_is_marked_and_future_schedule_is_not():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))  # Monday
    assert handled_marker_for_new_schedule(0, "11:00", now)
    assert handled_marker_for_new_schedule(0, "13:00", now) is None
    occurrence = occurrence_this_week(6, "20:00", now)
    assert occurrence.weekday() == 6
    assert occurrence.strftime("%H:%M") == "20:00"
