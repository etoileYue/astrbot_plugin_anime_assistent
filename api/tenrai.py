"""Tenrai API v1 客户端：用于获取 MAL 兼容的公开播出排期。"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

logger = logging.getLogger(__name__)

TENRAI_BASE_URL = "https://api.tenrai.org/v1"
# Tenrai 公共额度为 3 RPS；保守保持 1 RPS，避免批量 /sync 触发突发限制。
SEARCH_INTERVAL = 1.0
MAX_RETRIES = 3

_request_lock = asyncio.Lock()
_last_request_at = 0.0


def normalize_japanese_title(title: str) -> str:
    """按 Unicode NFKC 规范化并删除全部空白后做严格标题比较。"""
    import unicodedata

    normalized = unicodedata.normalize("NFKC", title or "")
    return "".join(char for char in normalized if not char.isspace())


@dataclass(frozen=True)
class BroadcastSchedule:
    mal_id: int
    airing: bool
    weekday: int | None = None  # Monday=0, already converted to Asia/Shanghai
    time: str = ""             # HH:MM, already converted to Asia/Shanghai


class TenraiClient:
    """带进程内限速及有限重试的异步 Tenrai API v1 客户端。"""

    def __init__(self, config=None):
        # Tenrai 与 Jikan v4 的搜索/响应结构兼容；沿用插件代理配置。
        proxy = getattr(config, "bangumi_proxy", "") if config else ""
        self._client = httpx.AsyncClient(
            base_url=TENRAI_BASE_URL,
            headers={"User-Agent": "etoile_yue/BangumiBot"},
            timeout=20.0,
            proxy=proxy or None,
        )

    async def _rate_limit(self):
        global _last_request_at
        async with _request_lock:
            now = time.monotonic()
            wait = SEARCH_INTERVAL - (now - _last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request_at = time.monotonic()

    async def _search(self, title: str) -> list[dict[str, Any]]:
        for attempt in range(MAX_RETRIES):
            await self._rate_limit()
            try:
                response = await self._client.get("/anime", params={"q": title, "limit": 5})
                if response.status_code == 429 and attempt < MAX_RETRIES - 1:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = min(float(retry_after), 10.0) if retry_after else 2 ** attempt
                    except ValueError:
                        wait = 2 ** attempt
                    logger.warning("Tenrai 请求过于频繁，%.1f 秒后重试", wait)
                    await asyncio.sleep(wait)
                    continue
                if response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
                return payload.get("data", [])
            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Tenrai 网络请求失败，重试 %s/%s：%s", attempt + 1, MAX_RETRIES, exc)
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
        return []

    @staticmethod
    def _to_shanghai(item: dict[str, Any]) -> BroadcastSchedule | None:
        mal_id = item.get("mal_id")
        airing = item.get("airing")
        # 不把缺失或非布尔的生命周期信息猜成「连载中」：这样查询结果异常时
        # 调用方会保留原有提醒，而不会误关或误开提醒。
        if not isinstance(mal_id, int) or mal_id <= 0 or not isinstance(airing, bool):
            return None

        # 完结条目常常没有完整 broadcast；airing=false 本身仍是有效的
        # 生命周期结论，不能因为缺少排期而丢失它。
        if not airing:
            return BroadcastSchedule(mal_id=mal_id, airing=False)

        broadcast = item.get("broadcast") or {}
        day = (broadcast.get("day") or "").strip()
        clock = (broadcast.get("time") or "").strip()
        tz_name = (broadcast.get("timezone") or "").strip()
        day_map = {
            "Mondays": 0, "Tuesdays": 1, "Wednesdays": 2, "Thursdays": 3,
            "Fridays": 4, "Saturdays": 5, "Sundays": 6,
        }
        if day not in day_map:
            return BroadcastSchedule(mal_id=mal_id, airing=True)
        try:
            hour, minute = map(int, clock.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            origin = ZoneInfo(tz_name)
            target = ZoneInfo("Asia/Shanghai")
        except (ValueError, ZoneInfoNotFoundError):
            return BroadcastSchedule(mal_id=mal_id, airing=True)

        # 2024-01-01 是星期一；转换后的 weekday 即是应保存的有效星期。
        local = datetime(2024, 1, 1 + day_map[day], hour, minute, tzinfo=origin)
        shanghai = local.astimezone(target)
        return BroadcastSchedule(
            mal_id=mal_id, airing=True, weekday=shanghai.weekday(),
            time=shanghai.strftime("%H:%M"),
        )

    async def find_exact_broadcast(self, japanese_title: str) -> BroadcastSchedule | None:
        """搜索前五项，返回日文原名严格匹配的排期与 airing 生命周期。"""
        wanted = normalize_japanese_title(japanese_title)
        if not wanted:
            return None
        for item in await self._search(japanese_title):
            if normalize_japanese_title(item.get("title_japanese") or "") != wanted:
                continue
            result = self._to_shanghai(item)
            if result is not None:
                return result
        return None

    async def close(self):
        await self._client.aclose()
