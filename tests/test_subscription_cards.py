"""追番列表封面缓存、补齐与 Pillow 卡片测试。"""

import asyncio
import base64
import io
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bangumibot.api.bangumi import CollectionItem, Subject
from bangumibot.core.sync import sync_from_bangumi
from bangumibot.handlers.subscription import SubscriptionHandler
from bangumibot.rendering import subscription_list as card_module
from bangumibot.rendering.subscription_list import (
    CANVAS_WIDTH,
    FOOTER_HEIGHT,
    HEADER_HEIGHT,
    ITEMS_PER_PAGE,
    MAX_IMAGE_BYTES,
    ROW_HEIGHT,
    ImageLoader,
    SubscriptionListRenderer,
    resolve_font_path,
)
from bangumibot.storage.database import Database
from bangumibot.storage.models import Subscription


class DummyConfig:
    bangumi_access_token = ""
    bangumi_mirror_url = ""
    bangumi_proxy = ""


def test_bundled_cjk_font_is_available_without_system_dependency():
    font_path = resolve_font_path()
    assert font_path is not None
    assert Path(font_path).name == "DroidSansFallbackFull.ttf"
    assert "assets/fonts" in Path(font_path).as_posix()


@pytest.mark.asyncio
async def test_old_database_migrates_cover_url(tmp_path):
    path = tmp_path / "bangumi.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY,
            subject_id INTEGER NOT NULL UNIQUE,
            subject_name TEXT NOT NULL,
            subject_name_cn TEXT,
            status INTEGER DEFAULT 3,
            total_eps INTEGER,
            last_notified_ep INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        "INSERT INTO subscriptions (subject_id, subject_name) VALUES (1, 'Test')"
    )
    connection.commit()
    connection.close()

    db = Database()
    await db.initialize(str(tmp_path))
    columns = await db.conn.execute_fetchall("PRAGMA table_info(subscriptions)")
    assert "cover_url" in {row[1] for row in columns}
    assert (await db.get_subscription(1)).cover_url is None
    await db.close()


@pytest.mark.asyncio
async def test_cover_url_only_replaced_by_nonempty_value(tmp_path):
    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Test", cover_url="https://img.test/old.jpg")
    await db.add_subscription(1, "Test 2", cover_url=None)
    assert (await db.get_subscription(1)).cover_url == "https://img.test/old.jpg"
    await db.update_cover_url(1, "")
    assert (await db.get_subscription(1)).cover_url == "https://img.test/old.jpg"
    await db.update_cover_url(1, "https://img.test/new.jpg")
    assert (await db.get_subscription(1)).cover_url == "https://img.test/new.jpg"
    await db.close()


@pytest.mark.asyncio
async def test_sync_selects_cover_and_preserves_cached_cover(monkeypatch, tmp_path):
    from bangumibot.core import sync

    class FakeClient:
        def __init__(self, config):
            pass

        async def get_watching_collections(self):
            return [
                CollectionItem(1, "Old", "", 12, 2, images=None),
                CollectionItem(
                    2,
                    "New",
                    "新番",
                    0,
                    3,
                    images={
                        "medium": "https://img.test/medium.jpg",
                        "common": "https://img.test/common.jpg",
                        "large": "https://img.test/large.jpg",
                    },
                ),
            ]

        async def get_collection(self, subject_id):
            return None

        async def close(self):
            pass

    db = Database()
    await db.initialize(str(tmp_path))
    await db.add_subscription(1, "Old", cover_url="https://img.test/cached.jpg")
    monkeypatch.setattr(sync, "BangumiClient", FakeClient)

    await sync_from_bangumi(db, DummyConfig())

    assert (await db.get_subscription(1)).cover_url == "https://img.test/cached.jpg"
    assert (await db.get_subscription(2)).cover_url == "https://img.test/large.jpg"
    await db.close()


@pytest.mark.asyncio
async def test_list_backfill_is_bounded_persists_success_and_closes(monkeypatch, tmp_path):
    from bangumibot.handlers import subscription

    class FakeClient:
        active = 0
        max_active = 0
        closed = False

        def __init__(self, config):
            pass

        async def get_subject(self, subject_id):
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            await asyncio.sleep(0.01)
            type(self).active -= 1
            if subject_id == 3:
                raise httpx.ReadTimeout("timeout")
            return Subject(
                subject_id,
                f"Title {subject_id}",
                "",
                "",
                0,
                images={"common": f"https://img.test/{subject_id}.jpg"},
            )

        async def close(self):
            type(self).closed = True

    db = Database()
    await db.initialize(str(tmp_path))
    for subject_id in range(1, 8):
        await db.add_subscription(subject_id, f"Title {subject_id}")
    monkeypatch.setattr(subscription, "BangumiClient", FakeClient)

    items = await SubscriptionHandler(db, DummyConfig()).get_subscription_items()

    assert len(items) == 7
    assert FakeClient.max_active == 4
    assert FakeClient.closed is True
    assert (await db.get_subscription(2)).cover_url == "https://img.test/2.jpg"
    assert (await db.get_subscription(3)).cover_url is None
    await db.close()


def _png_bytes(color: str = "#F3A6B8") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 48), color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_image_loader_accepts_png_and_rejects_unsafe_resources():
    calls = []

    def transport(request: httpx.Request):
        calls.append(str(request.url))
        if request.url.path == "/ok.png":
            return httpx.Response(200, content=_png_bytes())
        if request.url.path == "/large.png":
            return httpx.Response(
                200,
                headers={"Content-Length": str(MAX_IMAGE_BYTES + 1)},
                content=b"ignored",
            )
        if request.url.path == "/timeout.png":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=b"not an image")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        loader = ImageLoader(client)
        image = await loader.load("https://img.test/ok.png")
        assert image is not None and image.size == (32, 48)
        assert await loader.load("file:///etc/passwd") is None
        assert await loader.load("https://img.test/large.png") is None
        assert await loader.load("https://img.test/broken.png") is None
        assert await loader.load("https://img.test/timeout.png") is None

    assert all(not call.startswith("file:") for call in calls)


class PlaceholderLoader:
    async def load(self, url):
        return None


def _subscriptions(count: int) -> list[Subscription]:
    items = []
    for index in range(count):
        items.append(
            Subscription(
                subject_id=index + 1,
                subject_name=("とても長い日本語の原題" * 8) if index == 0 else f"Original {index}",
                subject_name_cn=("这是一部用于测试两行省略效果的超长中文标题" * 5) if index == 0 else f"番剧 {index}",
                status=(index % 5) + 1,
                watched_eps=18 if index == 0 else index,
                total_eps=12 if index == 0 else (0 if index % 2 else 24),
                airing=0 if index % 3 == 0 else 1,
                schedule_weekday=4 if index % 4 == 0 else None,
                schedule_time="23:30" if index % 4 == 0 else "",
                schedule_checked=index % 2 == 0,
                schedule_source="manual" if index % 5 == 0 else "",
            )
        )
    return items


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 6, 7, 13])
async def test_renderer_paginates_and_emits_decodable_png(count):
    font_path = resolve_font_path()
    if not font_path:
        pytest.skip("test environment has no CJK font")
    renderer = SubscriptionListRenderer(PlaceholderLoader(), font_path=font_path)

    payloads = await renderer.render_pages(_subscriptions(count))

    assert payloads is not None
    assert len(payloads) == (count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    for page_index, payload in enumerate(payloads):
        raw = base64.b64decode(payload, validate=True)
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(io.BytesIO(raw)) as image:
            page_items = min(ITEMS_PER_PAGE, count - page_index * ITEMS_PER_PAGE)
            assert image.size == (
                CANVAS_WIDTH,
                HEADER_HEIGHT + page_items * ROW_HEIGHT + FOOTER_HEIGHT,
            )


@pytest.mark.asyncio
async def test_renderer_retries_with_placeholders_then_falls_back(monkeypatch):
    font_path = resolve_font_path()
    if not font_path:
        pytest.skip("test environment has no CJK font")
    calls = []

    def fail_once(items, covers, path, **kwargs):
        calls.append(covers)
        if len(calls) == 1:
            raise OSError("cover draw failed")
        return "fallback-payload"

    monkeypatch.setattr(card_module, "_draw_page", fail_once)
    renderer = SubscriptionListRenderer(PlaceholderLoader(), font_path=font_path)
    assert await renderer.render_pages(_subscriptions(1)) == ["fallback-payload"]
    assert calls[1] == [None]

    monkeypatch.setattr(
        card_module,
        "_draw_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("draw failed")),
    )
    assert await renderer.render_pages(_subscriptions(1)) is None


@pytest.mark.asyncio
async def test_renderer_without_cjk_font_returns_none(monkeypatch):
    monkeypatch.setattr(card_module, "resolve_font_path", lambda configured="": None)
    renderer = SubscriptionListRenderer(PlaceholderLoader())
    assert await renderer.render_pages(_subscriptions(1)) is None


def test_plain_text_fallback_keeps_existing_schedule_semantics():
    items = _subscriptions(2)
    text = SubscriptionHandler.format_subscriptions_text(items)
    assert text.startswith("当前追番列表：")
    assert "🔄 " in text
    assert "每周五 23:30" not in text  # 第一个条目已完结，不追加排期文字。
    assert "未获取到自动排期" not in text  # 第二个条目仍处于排期查询中。
