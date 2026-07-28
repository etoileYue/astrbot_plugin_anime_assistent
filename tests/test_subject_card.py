"""/bgm 条目详情模型与卡片测试。"""

import base64
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bangumibot.api.bangumi import BangumiClient, Subject
from bangumibot.rendering.subject_card import (
    CANVAS_WIDTH,
    SubjectCardRenderer,
    _rating_counts,
    extract_infobox_field,
    format_subject_text,
)
from bangumibot.rendering.subscription_list import resolve_font_path


class DummyConfig:
    bangumi_access_token = ""
    bangumi_mirror_url = ""
    bangumi_proxy = ""


class PlaceholderLoader:
    async def load(self, _url):
        return None


def _subject() -> Subject:
    return Subject(
        id=400602,
        name="葬送のフリーレン",
        name_cn="葬送的芙莉莲",
        summary="这是一个用于验证详情卡排版的简介。" * 30,
        eps=28,
        total_episodes=28,
        subject_type=2,
        platform="TV",
        air_date="2023-09-29",
        rating={
            "score": 8.7,
            "rank": 41,
            "total": 123456,
            "count": {"10": 100, "9": 80, "8": 50, "7": 10, "1": 1},
        },
        tags=[
            {"name": "奇幻", "count": 10},
            {"name": "冒险", "count": 30},
            {"name": "治愈", "count": 20},
        ],
        infobox=[
            {"key": "导演", "value": [{"v": "斋藤圭一郎"}]},
            {"key": "动画制作", "value": "MADHOUSE"},
        ],
    )


@pytest.mark.asyncio
async def test_get_subject_keeps_detail_card_fields():
    client = BangumiClient(DummyConfig())

    async def fake_request(_method, _path, **_kwargs):
        return {
            "id": 1,
            "name": "Original",
            "name_cn": "中文名",
            "summary": "summary",
            "eps": 0,
            "total_episodes": 12,
            "type": 2,
            "platform": "Web",
            "date": "2026-01-01",
            "rating": {"score": 7.5},
            "images": {"large": "https://img.test/cover.jpg"},
            "tags": [{"name": "原创", "count": 9}],
            "infobox": [{"key": "导演", "value": "Test Director"}],
        }

    client._request = fake_request
    subject = await client.get_subject(1)

    assert subject.subject_type == 2
    assert subject.platform == "Web"
    assert subject.total_episodes == 12
    assert subject.tags == [{"name": "原创", "count": 9}]
    assert subject.infobox == [{"key": "导演", "value": "Test Director"}]


def test_infobox_and_text_fallback_use_selected_fields_only():
    subject = _subject()
    assert extract_infobox_field(subject.infobox, {"导演"}) == "斋藤圭一郎"
    assert extract_infobox_field(subject.infobox, {"监督"}) == "未知"

    text = format_subject_text(subject)
    assert "类型：动画 · 平台：TV" in text
    assert "评分：8.7（排名 #41，123,456 人评分）" in text
    assert "首播：2023-09-29 · 集数：共 28 集" in text
    assert "导演：斋藤圭一郎" in text
    assert "动画制作：MADHOUSE" in text
    assert "标签：冒险 · 治愈 · 奇幻" in text
    assert _rating_counts(subject) == {1: 1, 7: 10, 8: 50, 9: 80, 10: 100}


@pytest.mark.asyncio
async def test_subject_card_renders_a_decodable_png_with_placeholder_cover():
    font_path = resolve_font_path()
    if not font_path:
        pytest.skip("test environment has no CJK font")
    renderer = SubjectCardRenderer(PlaceholderLoader(), font_path=font_path)

    payload = await renderer.render(_subject())

    assert payload is not None
    raw = base64.b64decode(payload, validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        assert image.size == (CANVAS_WIDTH, 1450)
