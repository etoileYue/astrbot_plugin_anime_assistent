"""粉彩追番列表 PNG 渲染器。"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError

from ..core.schedule import WEEKDAY_NAMES
from ..storage.models import Subscription

logger = logging.getLogger(__name__)

CANVAS_WIDTH = 1600
HEADER_HEIGHT = 220
ROW_HEIGHT = 300
FOOTER_HEIGHT = 80
ITEMS_PER_PAGE = 6
COVER_SIZE = (168, 236)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000

BACKGROUND = "#FFF9F6"
CARD = "#FFFFFF"
PINK = "#F3A6B8"
PINK_LIGHT = "#FBE4EA"
MINT = "#9FD8C8"
MINT_LIGHT = "#E4F4EF"
TITLE = "#40383B"
MUTED = "#8B7E83"
TRACK = "#F1ECEA"
STATUS_LABELS = {1: "想看", 2: "看过", 3: "在看", 4: "搁置", 5: "抛弃"}

FONT_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_CANDIDATES = (
    str(FONT_ASSET_DIR / "DroidSansFallbackFull.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/local/share/fonts/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)
LATIN_FONT_CANDIDATES = (
    str(FONT_ASSET_DIR / "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
)


def _supports_cjk(path: str) -> bool:
    """用不同 CJK 字形的实际掩码排除只有 tofu 方框的字体。"""
    try:
        font = ImageFont.truetype(path, 36)
        glyphs = [bytes(font.getmask(char)) for char in ("追", "番", "あ")]
        return all(glyphs) and len(set(glyphs)) == len(glyphs)
    except Exception:
        return False


def resolve_font_path(configured_path: str = "") -> str | None:
    candidates = []
    if configured_path:
        candidates.append(str(Path(configured_path).expanduser()))
    candidates.extend(FONT_CANDIDATES)
    for candidate in candidates:
        if Path(candidate).is_file() and _supports_cjk(candidate):
            return candidate
    return None


def _decode_image(payload: bytes) -> Image.Image:
    with Image.open(io.BytesIO(payload)) as source:
        width, height = source.size
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError("image dimensions exceed safety limit")
        source.load()
        return ImageOps.exif_transpose(source).convert("RGBA")


class ImageLoader:
    """使用共享 httpx 客户端安全下载并在线程中解码封面。"""

    def __init__(self, client: httpx.AsyncClient, *, max_concurrency: int = 6):
        self._client = client
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def load(self, url: str | None) -> Image.Image | None:
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None

        try:
            async with self._semaphore:
                async with self._client.stream(
                    "GET", url, timeout=10.0, follow_redirects=True
                ) as response:
                    response.raise_for_status()
                    raw_length = response.headers.get("Content-Length", "").strip()
                    if raw_length.isdigit() and int(raw_length) > MAX_IMAGE_BYTES:
                        return None
                    payload = bytearray()
                    async for chunk in response.aiter_bytes(64 * 1024):
                        payload.extend(chunk)
                        if len(payload) > MAX_IMAGE_BYTES:
                            return None
            return await asyncio.to_thread(_decode_image, bytes(payload))
        except (
            httpx.HTTPError,
            TimeoutError,
            OSError,
            ValueError,
            UnidentifiedImageError,
        ) as exc:
            logger.info(
                "追番封面不可用 (host=%s): %s", parsed.hostname or "?", exc.__class__.__name__
            )
            return None


@lru_cache(maxsize=64)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=16)
def _latin_font_path(cjk_path: str) -> str:
    for candidate in LATIN_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return cjk_path


def _font_for_char(font: ImageFont.FreeTypeFont, char: str) -> ImageFont.FreeTypeFont:
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return font
    raw_path = font.path.decode() if isinstance(font.path, bytes) else str(font.path)
    return _font(_latin_font_path(raw_path), font.size)


def _font_segments(
    text: str, font: ImageFont.FreeTypeFont
) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    segments: list[tuple[str, ImageFont.FreeTypeFont]] = []
    for char in text:
        selected = _font_for_char(font, char)
        if segments and segments[-1][1] is selected:
            previous, _ = segments[-1]
            segments[-1] = (previous + char, selected)
        else:
            segments.append((char, selected))
    return segments


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return sum(draw.textlength(segment, font=segment_font)
               for segment, segment_font in _font_segments(text, font))


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    x, y = xy
    for segment, segment_font in _font_segments(text, font):
        draw.text((x, y), segment, font=segment_font, fill=fill)
        x += draw.textlength(segment, font=segment_font)


def _ellipsize(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> str:
    text = " ".join((text or "").split())
    if _text_width(draw, text, font) <= width:
        return text
    suffix = "…"
    while text and _text_width(draw, text + suffix, font) > width:
        text = text[:-1]
    return text.rstrip() + suffix


def _wrap_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    width: int,
    max_lines: int = 2,
) -> list[str]:
    text = " ".join((text or "未知条目").split())
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > width:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current = candidate
    if current or not lines:
        lines.append(current.rstrip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(draw, lines[-1] + "…", font, width)
    return lines


def _badge(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    foreground: str = TITLE,
) -> int:
    x, y = xy
    width = int(_text_width(draw, text, font)) + 34
    draw.rounded_rectangle((x, y, x + width, y + 46), radius=23, fill=fill)
    _draw_text(draw, (x + 17, y + 8), text, font, foreground)
    return width


def _schedule_text(sub: Subscription) -> str:
    if not sub.airing:
        return "已完结 · 更新提醒已停止"
    if sub.schedule_weekday is not None and sub.schedule_time:
        return f"每周{WEEKDAY_NAMES[sub.schedule_weekday]} {sub.schedule_time} 更新"
    if sub.schedule_source == "manual":
        return "更新提醒已关闭"
    if sub.schedule_checked:
        return "未获取到自动排期"
    return "排期查询中"


def _cover_image(
    cover: Image.Image | None,
    sub: Subscription,
    font_path: str,
) -> Image.Image:
    if cover is not None:
        fitted = ImageOps.fit(cover.convert("RGBA"), COVER_SIZE, method=Image.Resampling.LANCZOS)
    else:
        shades = ("#F8CED8", "#CBEAE1", "#F6DDB9", "#DCD4F3")
        fitted = Image.new("RGBA", COVER_SIZE, shades[sub.subject_id % len(shades)])
        draw = ImageDraw.Draw(fitted)
        title = (sub.subject_name_cn or sub.subject_name or "番").strip()
        initial = title[0] if title else "番"
        initial_font = _font(font_path, 68)
        selected_font = _font_for_char(initial_font, initial)
        box = draw.textbbox((0, 0), initial, font=selected_font)
        x = (COVER_SIZE[0] - (box[2] - box[0])) // 2
        y = (COVER_SIZE[1] - (box[3] - box[1])) // 2 - box[1]
        draw.text((x, y), initial, font=selected_font, fill="#6E5B62")
    mask = Image.new("L", COVER_SIZE, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *COVER_SIZE), radius=20, fill=255)
    fitted.putalpha(mask)
    return fitted


def _draw_page(
    items: list[Subscription],
    covers: list[Image.Image | None],
    font_path: str,
    *,
    page_number: int,
    page_count: int,
    total_count: int,
    airing_count: int,
) -> str:
    height = HEADER_HEIGHT + len(items) * ROW_HEIGHT + FOOTER_HEIGHT
    canvas = Image.new("RGBA", (CANVAS_WIDTH, height), BACKGROUND)

    # 柔和灯箱装饰与卡片阴影。
    decor = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    decor_draw = ImageDraw.Draw(decor)
    decor_draw.ellipse((1320, -120, 1640, 200), fill="#FBE4EACC")
    decor_draw.ellipse((-90, height - 210, 150, height + 30), fill="#E4F4EFCC")
    canvas = Image.alpha_composite(canvas, decor)
    draw = ImageDraw.Draw(canvas)

    header_font = _font(font_path, 64)
    count_font = _font(font_path, 30)
    page_font = _font(font_path, 28)
    title_font = _font(font_path, 42)
    original_font = _font(font_path, 27)
    meta_font = _font(font_path, 25)
    badge_font = _font(font_path, 23)
    progress_font = _font(font_path, 25)
    footer_font = _font(font_path, 22)

    draw.rounded_rectangle((62, 54, 78, 162), radius=8, fill=PINK)
    _draw_text(draw, (104, 52), "我的追番", header_font, TITLE)
    _draw_text(
        draw, (106, 137), f"共 {total_count} 部  ·  连载中 {airing_count} 部",
        count_font, MUTED,
    )
    page_text = f"{page_number} / {page_count}"
    page_width = int(_text_width(draw, page_text, page_font)) + 48
    draw.rounded_rectangle(
        (CANVAS_WIDTH - 70 - page_width, 82, CANVAS_WIDTH - 70, 134),
        radius=26, fill=MINT_LIGHT,
    )
    _draw_text(
        draw, (CANVAS_WIDTH - 46 - page_width, 91), page_text, page_font, "#47786B"
    )

    # 一次性模糊整页阴影，避免每个条目重复处理整张大画布。
    shadows = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadows)
    for index in range(len(items)):
        top = HEADER_HEIGHT + index * ROW_HEIGHT + 10
        bottom = top + 280
        shadow_draw.rounded_rectangle(
            (64, top + 7, 1536, bottom + 9), radius=30, fill="#8D65751F"
        )
    canvas = Image.alpha_composite(canvas, shadows.filter(ImageFilter.GaussianBlur(10)))
    draw = ImageDraw.Draw(canvas)

    for index, (sub, cover) in enumerate(zip(items, covers)):
        top = HEADER_HEIGHT + index * ROW_HEIGHT + 10
        bottom = top + 280
        draw.rounded_rectangle((60, top, 1540, bottom), radius=30, fill=CARD)

        canvas.alpha_composite(_cover_image(cover, sub, font_path), (88, top + 22))
        draw = ImageDraw.Draw(canvas)
        content_x = 290
        title = sub.subject_name_cn or sub.subject_name or "未知条目"
        for line_index, line in enumerate(_wrap_title(draw, title, title_font, 820, 2)):
            _draw_text(
                draw, (content_x, top + 25 + line_index * 51), line, title_font, TITLE
            )

        original = sub.subject_name if sub.subject_name_cn else ""
        if original and original != title:
            original = _ellipsize(draw, original, original_font, 800)
            _draw_text(draw, (content_x, top + 130), original, original_font, MUTED)

        _draw_text(
            draw, (content_x, top + 171), f"Bangumi ID  {sub.subject_id}",
            meta_font, MUTED,
        )

        status = STATUS_LABELS.get(sub.status, "未知")
        badge_x = 1160
        badge_x += _badge(
            draw, (badge_x, top + 30), status, badge_font, PINK_LIGHT, "#9D5264"
        ) + 14
        _badge(
            draw,
            (badge_x, top + 30),
            "连载中" if sub.airing else "已完结",
            badge_font,
            MINT_LIGHT if sub.airing else TRACK,
            "#47786B" if sub.airing else MUTED,
        )

        watched = sub.watched_eps
        if sub.total_eps > 0:
            progress_text = f"已看 {watched} / {sub.total_eps} 集"
            ratio = max(0.0, min(1.0, watched / sub.total_eps))
        else:
            progress_text = f"已看 {watched} 集"
            ratio = 0.0
        _draw_text(draw, (content_x, top + 222), progress_text, progress_font, TITLE)
        track_left, track_top, track_width = 510, top + 232, 470
        draw.rounded_rectangle(
            (track_left, track_top, track_left + track_width, track_top + 18),
            radius=9, fill=TRACK,
        )
        if ratio > 0:
            fill_width = max(18, int(track_width * ratio))
            draw.rounded_rectangle(
                (track_left, track_top, track_left + fill_width, track_top + 18),
                radius=9, fill=PINK,
            )
        schedule = _ellipsize(draw, _schedule_text(sub), progress_font, 470)
        schedule_width = int(_text_width(draw, schedule, progress_font))
        _draw_text(
            draw, (1498 - schedule_width, top + 222), schedule, progress_font, "#47786B"
        )

    footer_y = height - FOOTER_HEIGHT
    draw.line((80, footer_y + 10, 1520, footer_y + 10), fill="#EEDFE2", width=2)
    _draw_text(draw, (80, footer_y + 31), "BangumiBot · 粉彩追番灯箱", footer_font, MUTED)
    footer_page = f"第 {page_number} 页 / 共 {page_count} 页"
    footer_width = int(_text_width(draw, footer_page, footer_font))
    _draw_text(
        draw, (1520 - footer_width, footer_y + 31), footer_page, footer_font, MUTED
    )

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


class SubscriptionListRenderer:
    """下载封面并将结构化订阅分页渲染为 Base64 PNG。"""

    def __init__(self, image_loader: ImageLoader, *, font_path: str = ""):
        self._image_loader = image_loader
        self._render_slot = asyncio.Semaphore(1)
        self.font_path = resolve_font_path(font_path)
        self.last_failure_reason: str | None = None
        if not self.font_path:
            self.last_failure_reason = "未找到可用的 CJK 字体"
            logger.warning("%s，/sub list 将回退为纯文本", self.last_failure_reason)

    async def render_pages(self, items: list[Subscription]) -> list[str] | None:
        self.last_failure_reason = None
        if not items:
            return []
        if not self.font_path:
            self.last_failure_reason = "未找到可用的 CJK 字体"
            return None

        loaded = await asyncio.gather(
            *(self._image_loader.load(item.cover_url) for item in items),
            return_exceptions=True,
        )
        covers = [image if isinstance(image, Image.Image) else None for image in loaded]
        pages = [items[index:index + ITEMS_PER_PAGE] for index in range(0, len(items), ITEMS_PER_PAGE)]
        page_covers = [
            covers[index:index + ITEMS_PER_PAGE]
            for index in range(0, len(covers), ITEMS_PER_PAGE)
        ]
        total_pages = len(pages)
        airing_count = sum(bool(item.airing) for item in items)
        rendered: list[str] = []

        for number, (page, covers_for_page) in enumerate(zip(pages, page_covers), start=1):
            kwargs = {
                "page_number": number,
                "page_count": total_pages,
                "total_count": len(items),
                "airing_count": airing_count,
            }
            async with self._render_slot:
                try:
                    payload = await asyncio.to_thread(
                        _draw_page, page, covers_for_page, self.font_path, **kwargs
                    )
                except Exception as exc:
                    logger.warning(
                        "追番列表第 %s 页绘制失败，改用全占位封面重试: %s: %s",
                        number, exc.__class__.__name__, exc,
                    )
                    try:
                        payload = await asyncio.to_thread(
                            _draw_page, page, [None] * len(page), self.font_path, **kwargs
                        )
                    except Exception as retry_exc:
                        self.last_failure_reason = (
                            f"第 {number} 页占位重试失败："
                            f"{retry_exc.__class__.__name__}: {retry_exc}"
                        )
                        logger.error(
                            "追番列表第 %s 页占位重试失败，回退纯文本: %s: %s",
                            number, retry_exc.__class__.__name__, retry_exc,
                        )
                        return None
            if not payload:
                self.last_failure_reason = f"第 {number} 页渲染结果为空"
                return None
            rendered.append(payload)
        return rendered
