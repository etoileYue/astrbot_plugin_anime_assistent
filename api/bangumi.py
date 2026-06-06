"""Bangumi API v0 客户端。"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bgm.tv"
SEARCH_INTERVAL = 1.0
UPDATE_INTERVAL = 0.5
MAX_RETRIES = 3


class CollectionType:
    WISH = 1
    COLLECT = 2
    DO = 3
    ON_HOLD = 4
    DROPPED = 5


@dataclass
class Subject:
    id: int
    name: str
    name_cn: str
    summary: str
    eps: int
    rating: Optional[dict] = None
    images: Optional[dict] = None
    air_date: str = ""


@dataclass
class Episode:
    id: int
    ep: int
    name: str
    name_cn: str
    airdate: str


class BangumiClient:
    def __init__(self, config):
        self._config = config
        self._client = None
        self._last_search = 0.0
        self._last_update = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": "etoile_yue/BangumiBot"}
            token = self._get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    def _get_access_token(self) -> str:
        return ""

    async def _rate_limit(self, kind: str):
        if kind == "search":
            interval = SEARCH_INTERVAL
            now = asyncio.get_event_loop().time()
            wait = interval - (now - self._last_search)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_search = asyncio.get_event_loop().time()
        elif kind == "update":
            interval = UPDATE_INTERVAL
            now = asyncio.get_event_loop().time()
            wait = interval - (now - self._last_update)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_update = asyncio.get_event_loop().time()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        client = await self._get_client()
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.request(method, path, **kwargs)
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    wait = 2**attempt
                    logger.warning(f"Bangumi API 500, retry {attempt+1}/{MAX_RETRIES} in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                raise
            except httpx.RequestError as e:
                if attempt < MAX_RETRIES - 1:
                    wait = 2**attempt
                    logger.warning(f"Request error: {e}, retry {attempt+1}/{MAX_RETRIES} in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                raise

    async def search_subject(self, keyword: str) -> list[Subject]:
        await self._rate_limit("search")
        data = await self._request("POST", "/v0/search/subjects", json={"keyword": keyword, "limit": 5})
        results = []
        for item in data.get("data", []):
            results.append(Subject(
                id=item["id"],
                name=item.get("name", ""),
                name_cn=item.get("name_cn", ""),
                summary=item.get("summary", ""),
                eps=item.get("eps", 0) or 0,
                rating=item.get("rating"),
                images=item.get("images"),
                air_date=item.get("air_date", ""),
            ))
        return results

    async def get_subject(self, subject_id: int) -> Subject:
        data = await self._request("GET", f"/v0/subjects/{subject_id}")
        return Subject(
            id=data["id"],
            name=data.get("name", ""),
            name_cn=data.get("name_cn", ""),
            summary=data.get("summary", ""),
            eps=data.get("eps", 0) or 0,
            rating=data.get("rating"),
            images=data.get("images"),
            air_date=data.get("air_date", ""),
        )

    async def get_episodes(self, subject_id: int) -> list[Episode]:
        data = await self._request("GET", f"/v0/episodes", params={"subject_id": subject_id})
        results = []
        for item in data.get("data", []):
            results.append(Episode(
                id=item["id"],
                ep=item.get("ep", 0) or 0,
                name=item.get("name", ""),
                name_cn=item.get("name_cn", ""),
                airdate=item.get("airdate", ""),
            ))
        return results

    async def get_collection(self, subject_id: int) -> Optional[dict]:
        data = await self._request("GET", f"/v0/users/-/collections/{subject_id}")
        return data if data else None

    async def add_collection(self, subject_id: int, collection_type: int = CollectionType.DO) -> dict:
        await self._rate_limit("update")
        return await self._request(
            "POST",
            f"/v0/users/-/collections/{subject_id}",
            json={"type": collection_type},
        )

    async def update_collection(self, subject_id: int, **kwargs) -> dict:
        await self._rate_limit("update")
        return await self._request(
            "PATCH",
            f"/v0/users/-/collections/{subject_id}",
            json=kwargs,
        )

    async def mark_episode_watched(self, episode_id: int):
        await self._rate_limit("update")
        await self._request(
            "PUT",
            f"/v0/users/-/collections/-/episodes/{episode_id}",
            json={"type": 2},
        )

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
