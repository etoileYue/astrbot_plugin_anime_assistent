"""Bangumi 剧集页面评论爬虫。"""

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://bgm.tv"
CN_MIRROR_URL = "https://bangumi.one"
SCRAPE_INTERVAL = 0.5
MAX_RETRIES = 3
DEFAULT_CACHE_TTL = 86400  # 24h
DEFAULT_COMMENT_LIMIT = 30


@dataclass
class Comment:
    username: str
    text: str
    timestamp: str
    floor: int


class BangumiScraper:
    """爬取 Bangumi 剧集页面评论。"""

    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL,
                 comment_limit: int = DEFAULT_COMMENT_LIMIT,
                 use_cn_mirror: bool = False,
                 proxy: str | None = None):
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[int, tuple[float, list[Comment]]] = {}
        self._cache_ttl = cache_ttl
        self._comment_limit = comment_limit
        self._use_cn_mirror = use_cn_mirror
        self._proxy = proxy
        self._last_request = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            base_url = CN_MIRROR_URL if self._use_cn_mirror else BASE_URL
            proxies = None
            if self._proxy:
                proxies = {"http://": self._proxy, "https://": self._proxy}
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={"User-Agent": "etoile_yue/BangumiBot"},
                timeout=30.0,
                proxies=proxies,
            )
        return self._client

    async def _rate_limit(self):
        now = asyncio.get_event_loop().time()
        wait = SCRAPE_INTERVAL - (now - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = asyncio.get_event_loop().time()

    async def _request(self, path: str) -> str:
        client = await self._get_client()
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(path)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Bangumi HTML {e.response.status_code}, "
                        f"retry {attempt+1}/{MAX_RETRIES} in {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
            except httpx.RequestError as e:
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Scraper request error: {e}, "
                        f"retry {attempt+1}/{MAX_RETRIES} in {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

    def _parse_comments(self, html: str, limit: int) -> list[Comment]:
        soup = BeautifulSoup(html, "html.parser")
        comment_elements = soup.select('#comment_list div.row_reply[id^="post_"]')
        comments = []
        for el in comment_elements[:limit]:
            try:
                user_el = el.select_one("strong a.l")
                username = user_el.get_text(strip=True) if user_el else "未知用户"

                msg_el = el.select_one("div.message")
                text = msg_el.get_text(strip=True) if msg_el else ""

                floor_el = el.select_one("small a.floor-anchor")
                if floor_el:
                    floor_text = floor_el.get_text(strip=True)
                    parts = floor_text.split(" - ", 1)
                    floor_str = parts[0].lstrip("#") if parts else "0"
                    timestamp = parts[1] if len(parts) > 1 else ""
                    try:
                        floor = int(floor_str)
                    except ValueError:
                        floor = 0
                else:
                    timestamp = ""
                    floor = 0

                comments.append(Comment(
                    username=username,
                    text=text,
                    timestamp=timestamp,
                    floor=floor,
                ))
            except Exception:
                logger.warning("解析单条评论失败", exc_info=True)
                continue
        return comments

    async def get_episode_comments(
        self, episode_id: int, limit: int | None = None
    ) -> list[Comment]:
        """获取剧集评论，优先从缓存读取。limit 为 None 时使用实例默认值。"""
        if limit is None:
            limit = self._comment_limit
        now = time.time()
        if episode_id in self._cache:
            cached_time, cached_comments = self._cache[episode_id]
            if now - cached_time < self._cache_ttl:
                return cached_comments[:limit]
            del self._cache[episode_id]

        try:
            await self._rate_limit()
            html = await self._request(f"/ep/{episode_id}")
            comments = self._parse_comments(html, limit)
            self._cache[episode_id] = (now, comments)
            return comments
        except Exception:
            logger.warning(
                f"获取剧集评论失败 (episode_id={episode_id})", exc_info=True
            )
            return []

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
