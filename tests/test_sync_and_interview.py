"""云端范围同步与访谈评论时机测试。"""

import asyncio
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


class HandlerConfig(DummyConfig):
    scraper_comment_limit = 20
    use_cn_mirror = False
    bangumi_proxy = ""


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


@pytest.mark.asyncio
async def test_extend_unanswered_interview_replaces_question_and_persisted_range(tmp_path):
    """首问未答时扩展范围，问题与当前会话记录都必须同步更新。"""
    db = Database()
    await db.initialize(str(tmp_path))
    engine = InterviewEngine(
        plugin=None,
        db=db,
        config=DummyConfig(),
        subject_id=1,
        episode=18,
        start_episode=17,
        subject_name="Test",
    )
    # 本测试关注范围和持久化；不启动真实评论抓取。
    engine._start_comments_prefetch = lambda: None

    first_question = await engine.start("umo")
    updated_question = await engine.extend_to(20, "umo")

    assert "第17-18集" in first_question
    assert "第17-20集" in updated_question
    assert engine.episode == 20
    assert engine._history == [(updated_question, "")]
    rows = await db.get_interviews(1, 20)
    assert len(rows) == 1
    assert rows[0].episode_start == 17
    assert rows[0].question == updated_question
    assert await db.get_interviews(1, 18) == []
    await db.close()


@pytest.mark.asyncio
async def test_extend_answered_interview_keeps_history_and_updates_all_records(tmp_path):
    """已有回答后扩展范围，不应重发首问或丢失已有问答。"""
    db = Database()
    await db.initialize(str(tmp_path))
    engine = InterviewEngine(
        plugin=None,
        db=db,
        config=DummyConfig(),
        subject_id=1,
        episode=18,
        start_episode=17,
        subject_name="Test",
    )
    engine._start_comments_prefetch = lambda: None

    await engine.start("umo")

    async def fake_follow_up(answer, umo):
        return "追问"

    monkeypatch.setattr(engine, "_generate_follow_up", fake_follow_up)
    await engine.handle_answer("已有回答", "umo")
    updated_question = await engine.extend_to(20, "umo")

    assert updated_question is None
    assert engine.episode == 20
    assert engine.get_qa_pairs() == [(engine._history[0][0], "已有回答")]
    rows = await db.get_interviews(1, 20)
    assert len(rows) == 3
    assert {row.episode_start for row in rows} == {17}
    assert all(row.episode == 20 for row in rows)
    await db.close()


@pytest.mark.asyncio
async def test_handler_merges_same_subject_and_keeps_other_subjects(monkeypatch):
    """处理器为同番剧保留一个会话，同时不影响其他番剧的路由。"""
    from bangumibot.handlers import interview as interview_module

    class FakeEngine:
        def __init__(self, _plugin, _db, _config, subject_id, episode,
                     subject_name, subject_name_cn="", scraper=None,
                     start_episode=None):
            self.subject_id = subject_id
            self.start_episode = start_episode or episode
            self.episode = episode
            self.subject_name = subject_name_cn or subject_name
            self.state = None
            self.answered = False

        async def start(self, umo):
            return f"首问：第{self.start_episode}-{self.episode}集"

        async def extend_to(self, episode, umo):
            self.episode = episode
            if self.answered:
                return None
            return f"首问：第{self.start_episode}-{self.episode}集"

    monkeypatch.setattr(interview_module, "InterviewEngine", FakeEngine)
    handler = InterviewHandler(plugin=None, db=None, config=HandlerConfig())
    # 避免 FakeEngine 测试走真实 scraper 初始化分支。
    handler._scraper = object()

    first = await handler.try_start_auto("umo", 1, 18, "A", start_episode=17)
    merged = await handler.try_start_auto("umo", 1, 20, "A", start_episode=19)
    other = await handler.try_start_auto("umo", 2, 4, "B")

    assert first.status == "started"
    assert merged.status == "extended_pending"
    assert merged.question == "首问：第17-20集"
    assert len(handler._active_sessions) == 2
    assert handler._active_sessions[1].episode == 20
    hint = handler.get_routing_hint()
    assert "第17-20集" in hint
    assert "第4集" in hint
    assert handler.has_active_session(1, 17, 20)


@pytest.mark.asyncio
async def test_handler_ignores_covered_progress_and_preserves_started_session(monkeypatch):
    """相同或更旧的进度不重复创建会话；已有回答时只扩展范围。"""
    from bangumibot.handlers import interview as interview_module

    class FakeEngine:
        def __init__(self, _plugin, _db, _config, subject_id, episode,
                     subject_name, subject_name_cn="", scraper=None,
                     start_episode=None):
            self.subject_id = subject_id
            self.start_episode = start_episode or episode
            self.episode = episode
            self.subject_name = subject_name
            self.answered = False

        async def start(self, umo):
            return "首问"

        async def extend_to(self, episode, umo):
            self.episode = episode
            return None if self.answered else "更新后的首问"

    monkeypatch.setattr(interview_module, "InterviewEngine", FakeEngine)
    handler = InterviewHandler(plugin=None, db=None, config=HandlerConfig())
    handler._scraper = object()

    await handler.try_start_auto("umo", 1, 18, "A", start_episode=17)
    engine = handler._active_sessions[1]
    engine.answered = True
    extended = await handler.try_start_auto("umo", 1, 20, "A", start_episode=19)
    unchanged = await handler.try_start_auto("umo", 1, 18, "A", start_episode=17)

    assert extended.status == "extended_active"
    assert unchanged.status == "unchanged"
    assert len(handler._active_sessions) == 1


@pytest.mark.asyncio
async def test_handler_serializes_concurrent_same_subject_starts(monkeypatch):
    """并发的同番剧启动请求只能创建一个会话。"""
    from bangumibot.handlers import interview as interview_module

    class FakeEngine:
        starts = 0

        def __init__(self, _plugin, _db, _config, subject_id, episode,
                     subject_name, subject_name_cn="", scraper=None,
                     start_episode=None):
            self.subject_id = subject_id
            self.start_episode = start_episode or episode
            self.episode = episode
            self.subject_name = subject_name

        async def start(self, umo):
            type(self).starts += 1
            await asyncio.sleep(0)
            return "首问"

        async def extend_to(self, episode, umo):
            self.episode = episode
            return "更新后的首问"

    monkeypatch.setattr(interview_module, "InterviewEngine", FakeEngine)
    handler = InterviewHandler(plugin=None, db=None, config=HandlerConfig())
    handler._scraper = object()

    first, second = await asyncio.gather(
        handler.try_start_auto("umo", 1, 18, "A", start_episode=17),
        handler.try_start_auto("umo", 1, 18, "A", start_episode=17),
    )

    assert FakeEngine.starts == 1
    assert {first.status, second.status} == {"started", "unchanged"}
    assert len(handler._active_sessions) == 1
