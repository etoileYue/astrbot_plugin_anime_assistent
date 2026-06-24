"""Bangumi API v0 客户端。"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bgm.tv"
CN_MIRROR_URL = "https://api.bangumi.one"
SEARCH_INTERVAL = 1.0
UPDATE_INTERVAL = 0.5
MAX_RETRIES = 3


class CollectionType:
    WISH = 1
    DONE = 2
    DOING = 3
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


@dataclass
class CollectionItem:
    subject_id: int
    subject_name: str
    subject_name_cn: str
    eps: int
    ep_status: int


class BangumiClient:
    def __init__(self, config):
        self._config = config
        self._client = None
        self._username: Optional[str] = None
        self._last_search = 0.0
        self._last_update = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": "etoile_yue/BangumiBot"}
            token = self._get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            base_url = self._config.bangumi_mirror_url or BASE_URL
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    def _get_access_token(self) -> str:
        return self._config.bangumi_access_token

    async def _get_username(self) -> str:
        if self._username is None:
            data = await self._request("GET", "/v0/me")
            self._username = data["username"]
        return self._username

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
                air_date=item.get("date", ""),
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
            air_date=data.get("date", ""),
        )

    async def get_episodes(self, subject_id: int) -> list[Episode]:
        if not isinstance(subject_id, int) or subject_id <= 0:
            raise ValueError(f"subject_id must be a positive int, got {subject_id!r}")
        all_items: list[Episode] = []
        offset = 0
        limit = 200
        while True:
            data = await self._request(
                "GET", "/v0/episodes",
                params={"subject_id": subject_id, "limit": limit, "offset": offset},
            )
            for item in data.get("data", []):
                all_items.append(Episode(
                    id=item["id"],
                    ep=item.get("ep", 0) or 0,
                    name=item.get("name", ""),
                    name_cn=item.get("name_cn", ""),
                    airdate=item.get("airdate", ""),
                ))
            total = data.get("total", 0)
            offset += limit
            if offset >= total:
                break
        return all_items

    async def get_collection(self, subject_id: int) -> Optional[dict]:
        username = await self._get_username()
        data = await self._request("GET", f"/v0/users/{username}/collections/{subject_id}")
        return data if data else None

    async def get_watching_collections(self) -> list[CollectionItem]:
        """分页获取所有「在看」(type=3) 收藏。"""
        username = await self._get_username()
        await self._rate_limit("search")
        all_items: list[CollectionItem] = []
        offset = 0
        limit = 50
        while True:
            data = await self._request(
                "GET",
                f"/v0/users/{username}/collections",
                params={"type": 3, "limit": limit, "offset": offset},
            )
            for item in data.get("data", []):
                subject = item.get("subject", {})
                all_items.append(CollectionItem(
                    subject_id=item.get("subject_id", subject.get("id", 0)),
                    subject_name=subject.get("name", ""),
                    subject_name_cn=subject.get("name_cn", ""),
                    eps=subject.get("eps", 0) or 0,
                    ep_status=item.get("ep_status", 0),
                ))
            total = data.get("total", 0)
            offset += limit
            if offset >= total:
                break
            await self._rate_limit("search")
        return all_items

    async def add_collection(self, subject_id: int, collection_type: int = CollectionType.DOING) -> dict:
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
