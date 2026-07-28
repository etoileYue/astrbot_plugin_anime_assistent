"""Bangumi 单条目详情 PNG 卡片。"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..api.bangumi import Subject, select_cover_url
from .subscription_list import (
    ImageLoader,
    _draw_text,
    _ellipsize,
    _font,
    _text_width,
    resolve_font_path,
)

logger = logging.getLogger(__name__)

CANVAS_WIDTH = 1600
COVER_SIZE = (410, 578)
MAX_SUMMARY_LINES = 6

BACKGROUND = "#FFF9F6"
CARD = "#FFFFFF"
TITLE = "#40383B"
MUTED = "#8B7E83"
PINK = "#F3A6B8"
PINK_LIGHT = "#FBE4EA"
MINT = "#9FD8C8"
MINT_LIGHT = "#E4F4EF"
LINE = "#EEE4E2"

SUBJECT_TYPES = {
    1: "书籍",
    2: "动画",
    3: "音乐",
    4: "游戏",
    6: "三次元",
}
DIRECTOR_KEYS = {"导演", "监督", "監督", "总导演"}
ANIMATION_STUDIO_KEYS = {"动画制作", "动画制作公司"}


def _normalise_text(value: object, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    return " ".join(value.split()) or default


def _summary_excerpt(value: object, limit: int = 360) -> str:
    text = _normalise_text(value, "暂无简介")
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    width: int,
    max_lines: int,
) -> list[str]:
    text = _normalise_text(text, "暂无简介")
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > width:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    if not lines:
        lines = ["暂无简介"]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(draw, lines[-1] + "…", font, width)
    return lines


def _infobox_value(value: object) -> str:
    if isinstance(value, str):
        return _normalise_text(value)
    if not isinstance(value, list):
        return ""
    values: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = _normalise_text(item.get("v"))
        if text and text not in values:
            values.append(text)
    return "、".join(values)


def extract_infobox_field(infobox: Iterable[object], keys: set[str]) -> str:
    """从 v0 infobox 中提取指定键，兼容字符串与键值数组。"""
    for entry in infobox:
        if not isinstance(entry, dict):
            continue
        key = _normalise_text(entry.get("key"))
        if key in keys:
            value = _infobox_value(entry.get("value"))
            if value:
                return value
    return "未知"


def _top_tags(tags: Iterable[object], limit: int = 6) -> list[str]:
    indexed: list[tuple[int, int, str]] = []
    for index, tag in enumerate(tags):
        if not isinstance(tag, dict):
            continue
        name = _normalise_text(tag.get("name"))
        if not name:
            continue
        count = tag.get("count", 0)
        indexed.append((count if isinstance(count, int) else 0, index, name))
    indexed.sort(key=lambda item: (-item[0], item[1]))
    selected: list[str] = []
    for _, _, name in indexed:
        if name not in selected:
            selected.append(name)
        if len(selected) >= limit:
            break
    return selected


def _cover_image(cover: Image.Image | None, subject: Subject, font_path: str) -> Image.Image:
    if cover is not None:
        image = ImageOps.fit(cover.convert("RGBA"), COVER_SIZE, method=Image.Resampling.LANCZOS)
    else:
        image = Image.new("RGBA", COVER_SIZE, PINK_LIGHT if subject.id % 2 else MINT_LIGHT)
        draw = ImageDraw.Draw(image)
        initial = (subject.name_cn or subject.name or "番").strip()[:1] or "番"
        font = _font(font_path, 140)
        bbox = draw.textbbox((0, 0), initial, font=font)
        x = (COVER_SIZE[0] - (bbox[2] - bbox[0])) // 2
        y = (COVER_SIZE[1] - (bbox[3] - bbox[1])) // 2 - bbox[1]
        _draw_text(draw, (x, y), initial, font, "#6E5B62")

    mask = Image.new("L", COVER_SIZE, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *COVER_SIZE), radius=26, fill=255)
    image.putalpha(mask)
    return image


def _badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> int:
    width = int(_text_width(draw, text, font)) + 34
    draw.rounded_rectangle((x, y, x + width, y + 44), radius=22, fill=fill)
    _draw_text(draw, (x + 17, y + 7), text, font, TITLE)
    return width


def _info_value(subject: Subject, name: str) -> str:
    if name == "类型":
        return SUBJECT_TYPES.get(subject.subject_type, "未知")
    if name == "平台":
        return _normalise_text(subject.platform, "未知")
    if name == "首播":
        return _normalise_text(subject.air_date, "未知")
    if name == "集数":
        total = subject.eps or subject.total_episodes
        return f"共 {total} 集" if total else "未知"
    if name == "导演":
        return extract_infobox_field(subject.infobox, DIRECTOR_KEYS)
    if name == "动画制作":
        return extract_infobox_field(subject.infobox, ANIMATION_STUDIO_KEYS)
    return "未知"


def _rating_text(subject: Subject) -> tuple[str, str, str]:
    rating = subject.rating if isinstance(subject.rating, dict) else {}
    score = rating.get("score")
    score_text = f"{score:.1f}" if isinstance(score, (int, float)) and score > 0 else "--"
    rank = rating.get("rank")
    rank_text = f"排名 #{rank}" if isinstance(rank, int) and rank > 0 else "排名 --"
    total = rating.get("total")
    total_text = f"{total:,} 人评分" if isinstance(total, int) and total > 0 else "暂无评分"
    return score_text, rank_text, total_text


def _rating_counts(subject: Subject) -> dict[int, int]:
    rating = subject.rating if isinstance(subject.rating, dict) else {}
    raw_counts = rating.get("count")
    if not isinstance(raw_counts, dict):
        return {}
    counts: dict[int, int] = {}
    for score in range(1, 11):
        value = raw_counts.get(str(score), raw_counts.get(score, 0))
        if isinstance(value, int) and value > 0:
            counts[score] = value
    return counts


def _draw_rating_histogram(
    draw: ImageDraw.ImageDraw,
    subject: Subject,
    x: int,
    y: int,
    font_path: str,
) -> None:
    """在评分区右侧绘制 10→1 分的柔和柱状图。"""
    label_font = _font(font_path, 22)
    axis_font = _font(font_path, 20)
    counts = _rating_counts(subject)
    _draw_text(draw, (x, y), "评分分布", label_font, MUTED)

    baseline = y + 128
    chart_x = x + 4
    bar_width = 31
    gap = 8
    max_height = 84
    draw.line((chart_x, baseline, chart_x + 10 * (bar_width + gap) - gap, baseline), fill=LINE, width=2)
    if not counts:
        _draw_text(draw, (x, y + 52), "暂无分布数据", label_font, MUTED)
        return

    max_count = max(counts.values())
    for index, score in enumerate(range(10, 0, -1)):
        count = counts.get(score, 0)
        bar_x = chart_x + index * (bar_width + gap)
        if count:
            height = max(7, round(max_height * count / max_count))
            draw.rounded_rectangle(
                (bar_x, baseline - height, bar_x + bar_width, baseline),
                radius=7,
                fill=PINK,
            )
        label = str(score)
        label_width = _text_width(draw, label, axis_font)
        _draw_text(
            draw,
            (int(bar_x + (bar_width - label_width) / 2), baseline + 10),
            label,
            axis_font,
            MUTED,
        )


def format_subject_text(subject: Subject) -> str:
    """图片不可用时的详情文本，与卡片保持相同字段范围。"""
    score, rank, total = _rating_text(subject)
    title = subject.name_cn or subject.name or "未知条目"
    original = subject.name if subject.name and subject.name != title else ""
    lines = [f"《{title}》 [#{subject.id}]"]
    if original:
        lines.append(original)
    lines.extend([
        f"类型：{_info_value(subject, '类型')} · 平台：{_info_value(subject, '平台')}",
        f"评分：{score}（{rank}，{total}）",
        f"首播：{_info_value(subject, '首播')} · 集数：{_info_value(subject, '集数')}",
        f"导演：{_info_value(subject, '导演')}",
        f"动画制作：{_info_value(subject, '动画制作')}",
    ])
    tags = _top_tags(subject.tags)
    if tags:
        lines.append("标签：" + " · ".join(tags))
    lines.append("简介：" + _summary_excerpt(subject.summary))
    return "\n".join(lines)


def _draw_card(subject: Subject, cover: Image.Image | None, font_path: str) -> str:
    canvas = Image.new("RGB", (CANVAS_WIDTH, 1450), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((48, 42, 1552, 1408), radius=34, fill=CARD)
    draw.rounded_rectangle((48, 42, 1552, 58), radius=8, fill=PINK)

    title_font = _font(font_path, 58)
    original_font = _font(font_path, 30)
    label_font = _font(font_path, 27)
    value_font = _font(font_path, 34)
    score_font = _font(font_path, 78)
    body_font = _font(font_path, 30)
    footer_font = _font(font_path, 24)

    cover_image = _cover_image(cover, subject, font_path)
    canvas.paste(cover_image, (100, 110), cover_image)
    content_x = 570
    title = _normalise_text(subject.name_cn or subject.name, "未知条目")
    title_lines = _wrap_text(draw, title, title_font, 880, 2)
    for index, line in enumerate(title_lines):
        _draw_text(draw, (content_x, 105 + index * 75), line, title_font, TITLE)
    title_bottom = 105 + len(title_lines) * 75
    original = _normalise_text(subject.name)
    if original and original != title:
        _draw_text(draw, (content_x, title_bottom + 5), _ellipsize(draw, original, original_font, 880), original_font, MUTED)
        title_bottom += 42

    badge_y = title_bottom + 26
    first = _badge(draw, content_x, badge_y, _info_value(subject, "类型"), label_font, PINK_LIGHT)
    _badge(draw, content_x + first + 16, badge_y, _info_value(subject, "平台"), label_font, MINT_LIGHT)

    score, rank, total = _rating_text(subject)
    rating_y = badge_y + 88
    _draw_text(draw, (content_x, rating_y), "Bangumi 评分", label_font, MUTED)
    _draw_text(draw, (content_x, rating_y + 30), score, score_font, PINK)
    _draw_text(draw, (content_x + 170, rating_y + 54), rank, label_font, TITLE)
    _draw_text(draw, (content_x + 170, rating_y + 91), total, label_font, MUTED)
    _draw_rating_histogram(draw, subject, content_x + 500, rating_y + 10, font_path)

    info_y = rating_y + 185
    info_rows = [
        ("首播日期", _info_value(subject, "首播")),
        ("总集数", _info_value(subject, "集数")),
        ("导演", _info_value(subject, "导演")),
        ("动画制作", _info_value(subject, "动画制作")),
    ]
    for index, (label, value) in enumerate(info_rows):
        y = info_y + index * 58
        _draw_text(draw, (content_x, y), label, label_font, MUTED)
        _draw_text(draw, (content_x + 175, y - 3), _ellipsize(draw, value, value_font, 700), value_font, TITLE)

    tags_y = 850
    _draw_text(draw, (100, tags_y), "热门标签", label_font, MUTED)
    badge_x = 100
    for tag in _top_tags(subject.tags):
        width = int(_text_width(draw, tag, label_font)) + 34
        if badge_x + width > 1500:
            break
        _badge(draw, badge_x, tags_y + 42, tag, label_font, MINT_LIGHT)
        badge_x += width + 14

    summary_y = 980
    draw.line((100, summary_y - 28, 1500, summary_y - 28), fill=LINE, width=2)
    _draw_text(draw, (100, summary_y), "简介", label_font, MUTED)
    for index, line in enumerate(_wrap_text(draw, subject.summary, body_font, 1400, MAX_SUMMARY_LINES)):
        _draw_text(draw, (100, summary_y + 45 + index * 48), line, body_font, TITLE)

    _draw_text(draw, (100, 1365), f"BangumiBot · Subject #{subject.id}", footer_font, MUTED)
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


class SubjectCardRenderer:
    """下载封面并渲染单条目详情卡。"""

    def __init__(self, image_loader: ImageLoader, *, font_path: str = ""):
        self._image_loader = image_loader
        self.font_path = resolve_font_path(font_path)
        self.last_failure_reason: str | None = None

    async def render(self, subject: Subject) -> str | None:
        self.last_failure_reason = None
        if not self.font_path:
            self.last_failure_reason = "未找到可用的 CJK 字体"
            return None
        cover = await self._image_loader.load(select_cover_url(subject.images))
        try:
            return await asyncio.to_thread(_draw_card, subject, cover, self.font_path)
        except Exception as exc:
            self.last_failure_reason = f"卡片绘制失败：{exc.__class__.__name__}"
            logger.warning("条目详情卡绘制失败: %s", exc, exc_info=True)
            return None
