"""云端范围同步与访谈评论时机测试。"""

import sys
from pathlib import Path

import pytest

# 生产代码使用包内相对导入；测试从仓库根目录运行时补上其父目录。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bangumibot.api.bangumi import CollectionItem, CollectionType, Episode
from bangumibot.core.interview_engine import InterviewEngine
from bangumibot.core.sync import sync_from_bangumi
from bangumibot.handlers.interview import InterviewHandler
from bangumibot.scraper.bangumi import Comment
from bangumibot.storage.database import Database


class DummyConfig:
    max_interview_rounds = 3


def test_range_routing_parser_keeps_both_endpoints():
    handler = object.__new__(InterviewHandler)

    route = handler._parse_routing("[Test] 11-12：这是我的总结")

    assert route is not None
    assert route.identifier == "Test"
    assert route.start_episode == 11
    assert route.end_episode == 12
    assert route.answer == "这是我的总结"


class FakeSyncClient:
    collections: list[CollectionItem] = []
    collection_details: dict[int, dict] = {}

    def __init__(self, config):
        pass

    async def get_watching_collections(self):
        return self.collections

    async def get_episodes(self, subject_id):
        return []

    async def get_collection(self, subject_id):
        return self.collection_details.get(subject_id)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_sync_reports_full_missing_range(monkeypatch, tmp_path):
    from bangumibot.core import sync

    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Test", total_eps=12, watched_eps=10)
    FakeSyncClient.collections = [
        CollectionItem(1, "Test", "", 12, 12),
    ]
    FakeSyncClient.collection_details = {}
    monkeypatch.setattr(sync, "BangumiClient", FakeSyncClient)

    *_, diffs = await sync_from_bangumi(db, DummyConfig())

    assert diffs == [{
        "subject_id": 1,
        "subject_name": "Test",
        "subject_name_cn": "",
        "start_episode": 11,
        "end_episode": 12,
        "bangumi_eps": 12,
        "local_eps": 10,
    }]
    await db.close()


@pytest.mark.asyncio
async def test_done_collection_uses_total_when_ep_status_missing(monkeypatch, tmp_path):
    from bangumibot.core import sync

    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Test", total_eps=12, watched_eps=10)
    FakeSyncClient.collections = []
    FakeSyncClient.collection_details = {
        1: {"type": CollectionType.DONE, "ep_status": 0, "subject": {"eps": 12}},
    }
    monkeypatch.setattr(sync, "BangumiClient", FakeSyncClient)

    *_, diffs = await sync_from_bangumi(db, DummyConfig())

    assert len(diffs) == 1
    assert diffs[0]["start_episode"] == 11
    assert diffs[0]["end_episode"] == 12
    await db.close()


@pytest.mark.asyncio
async def test_initial_message_is_fixed_and_follow_up_uses_comments(monkeypatch):
    engine = InterviewEngine(
        plugin=None,
        db=None,
        config=DummyConfig(),
        subject_id=1,
        episode=12,
        start_episode=11,
        subject_name="Test",
        scraper=object(),
    )
    calls = []

    async def fake_chat(prompt, umo, context=None):
        calls.append((prompt, context))
        return "问题"

    monkeypatch.setattr(engine, "_llm_chat", fake_chat)
    engine._comments_context = "第11集：\n- user: 评论内容"

    initial_message = await engine._generate_initial_question("umo")
    assert "评论内容" not in initial_message
    assert "第11-12集" in initial_message
    assert calls == []

    engine._history = [("首问", "这是我的自主总结")]
    await engine._generate_follow_up("这是我的自主总结", "umo")
    prompt, context = calls[0]
    # 追问提示本身必须包含回答，不能只依赖 AstrBot provider 是否传递 context。
    assert "这是我的自主总结" in prompt
    assert "追问阶段" in prompt
    assert "绝不能重新询问整体感受" in prompt
    assert "评论内容" in prompt
    assert "最新用户回答开始" in prompt
    assert context == [
        {"role": "assistant", "content": "首问"},
        {"role": "user", "content": "这是我的自主总结"},
    ]


@pytest.mark.asyncio
async def test_range_comment_fetches_each_episode(monkeypatch):
    from bangumibot.api import bangumi

    class FakeInterviewClient:
        def __init__(self, config):
            pass

        async def get_episodes(self, subject_id):
            return [
                Episode(101, 11, "", "", ""),
                Episode(102, 12, "", "", ""),
            ]

        async def close(self):
            pass

    class FakeScraper:
        def __init__(self):
            self.requested = []

        async def get_episode_comments(self, episode_id):
            self.requested.append(episode_id)
            return [Comment("user", f"comment-{episode_id}", "", 1)]

    monkeypatch.setattr(bangumi, "BangumiClient", FakeInterviewClient)
    scraper = FakeScraper()
    engine = InterviewEngine(
        plugin=None,
        db=None,
        config=DummyConfig(),
        subject_id=1,
        episode=12,
        start_episode=11,
        subject_name="Test",
        scraper=scraper,
    )

    context = await engine._fetch_comments_context()

    assert scraper.requested == [101, 102]
    assert "第11集：" in context
    assert "第12集：" in context
