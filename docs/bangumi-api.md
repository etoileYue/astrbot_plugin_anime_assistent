# Bangumi API 封装设计

## 概述

Bangumi API v0 是 bgm.tv 提供的 REST API，用于查询番剧信息、管理收藏和同步观看进度。

- **API 文档**：https://github.com/bangumi/api
- **Base URL**：`https://api.bgm.tv`
- **认证方式**：Personal Access Token (Bearer)
- **数据格式**：JSON

## 认证方式

访问 https://next.bgm.tv/demo/access-token 获取个人 Access Token。将 Token 配置到插件的 `bangumi_access_token` 字段即可。

所有需要认证的请求在 Header 中携带：
```
Authorization: Bearer {access_token}
```

## 封装设计

### 类结构

```python
# api/bangumi.py

from dataclasses import dataclass
from typing import Optional
from enum import IntEnum

class CollectionType(IntEnum):
    WISH = 1       # 想看
    COLLECT = 2    # 看过
    DO = 3         # 在看
    ON_HOLD = 4    # 搁置
    DROPPED = 5    # 抛弃

class EpisodeStatus(IntEnum):
    REMOVE = 0     # 移除
    QUEUE = 1      # 想看
    WATCHED = 2    # 看过
    DROP = 3       # 抛弃

@dataclass
class Subject:
    id: int
    name: str              # 默认名称
    name_cn: str           # 中文名
    summary: str           # 简介
    eps: int               # 总集数
    rating: Optional[dict] # 评分信息
    images: Optional[dict] # 图片

@dataclass
class Episode:
    id: int                # 章节ID（API用）
    ep: int                # 集数（第几集）
    name: str              # 标题
    name_cn: str           # 中文标题
    airdate: str           # 播出日期

class BangumiClient:
    """Bangumi API v0 客户端"""

    def __init__(self, config: PluginConfig):
        ...

    # === 条目 ===
    async def search_subject(self, keyword: str) -> list[Subject]: ...
    async def get_subject(self, subject_id: int) -> Subject: ...
    async def get_episodes(self, subject_id: int) -> list[Episode]: ...

    # === 收藏 ===
    async def get_collection(self, subject_id: int) -> dict: ...
    async def add_collection(self, subject_id: int, type: CollectionType = CollectionType.DO) -> dict: ...
    async def update_collection(self, subject_id: int, **kwargs) -> dict: ...

    # === 章节进度 ===
    async def get_episode_status(self, episode_id: int) -> dict: ...
    async def mark_episode_watched(self, episode_id: int): ...

    # === 用户 ===
    async def get_my_collections(self, type: Optional[CollectionType] = None) -> list[dict]: ...
```

### 核心 API 端点

| 方法 | 端点 | 说明 | 认证 |
|------|------|------|------|
| `POST` | `/v0/search/subjects` | 搜索条目 | 可选 |
| `GET` | `/v0/subjects/{id}` | 条目详情 | 可选 |
| `GET` | `/v0/episodes?subject_id={id}` | 章节列表 | 可选 |
| `GET` | `/v0/users/-/collections/{id}` | 获取收藏详情 | 必需 |
| `POST` | `/v0/users/-/collections/{id}` | 添加到收藏 | 必需 |
| `PATCH` | `/v0/users/-/collections/{id}` | 更新收藏状态 | 必需 |
| `PUT` | `/v0/users/-/collections/-/episodes/{ep_id}` | 更新单集状态 | 必需 |
| `PATCH` | `/v0/users/-/collections/{id}/episodes` | 批量更新章节 | 必需 |

### 频率限制

Bangumi API 有频率限制。建议：

- 搜索接口：每次请求间隔 >= 1 秒
- 更新接口：每次请求间隔 >= 0.5 秒
- 使用 `asyncio.sleep()` 控制

## 关键接口调用示例

### 更新观看进度

```python
# 1. 获取章节列表
episodes = await client.get_episodes(subject_id=400602)
# 返回：[Episode(id=12345, ep=1, ...), Episode(id=12346, ep=2, ...)]

# 2. 找到目标集数对应的 episode_id
target = next(e for e in episodes if e.ep == 15)

# 3. 标记为看过
await client.mark_episode_watched(episode_id=target.id)
```

### 搜索番剧

```python
# POST /v0/search/subjects
results = await client.search_subject("葬送的芙莉莲")
# 返回：[Subject(id=400602, name="葬送のフリーレン", name_cn="葬送的芙莉莲", ...)]
```

## 注意事项（踩坑指南）

1. **必须先收藏才能更新进度**
   - 调用 `PATCH /v0/users/-/collections/{id}/episodes` 时，如果条目未在收藏中，返回 400 错误
   - 错误信息：`"you need to add subject to your collection first"`
   - 解决方案：先调 `POST /v0/users/-/collections/{id}` 添加到收藏

2. **章节 ID ≠ 集数**
   - `episode_id` 是 Bangumi 内部的章节 ID，不是第几集
   - 必须通过 `GET /v0/episodes?subject_id=X` 获取映射关系

3. **已知 Bug**
   - 章节更新接口偶有 500 错误（服务端已知问题）
   - 评分更新偶有失败
   - 建议加重试机制（最多 3 次，指数退避）

4. **Token 失效**
   - 个人 Access Token 不会自动过期
   - 如遇 401 错误，检查 Token 是否被手动撤销，重新从 https://next.bgm.tv/demo/access-token 获取

5. **异步要求**
   - AstrBot 要求使用异步 HTTP 库（httpx / aiohttp）
   - 不要使用 `requests` 库

## 剧集评论爬取（HTML 解析）

### 背景

Bangumi API v0 **没有**提供剧集评论/讨论的端点。但 Bangumi 的剧集页面（`https://bgm.tv/ep/{episode_id}`）包含「吐槽箱」——用户对该集内容的评论讨论，这些评论在服务端渲染到 HTML 中，可直接爬取解析。

### 数据来源

- **URL 模式**：`https://bgm.tv/ep/{episode_id}`
- **episode_id**：通过 `GET /v0/episodes?subject_id={subject_id}` 获取，与 API 中的 `Episode.id` 一致
- **加载方式**：所有评论在初始 HTML 中渲染（`div#comment_list`），无需 AJAX 翻页

### HTML 结构

每条评论的结构如下（在 `div#comment_list` 内）：

```html
<div id="post_{id}" class="... row_reply clearit" data-item-user="{username}">
  <div class="post_actions re_info">
    <div class="action">
      <small><a href="#post_{id}" class="floor-anchor">#N</a> - 2023-6-29 23:22</small>
    </div>
  </div>
  <a href="/user/{username}" class="avatar">...</a>
  <div class="inner">
    <strong><a href="/user/{username}" class="l post_author_{id}">{display_name}</a></strong>
    <div class="reply_content">
      <div class="message clearit">{评论文本}</div>
    </div>
  </div>
</div>
```

**BeautifulSoup 选择器：**

| 字段 | 选择器 | 说明 |
|------|--------|------|
| 评论容器 | `#comment_list div.row_reply[id^="post_"]` | 每条主评论 |
| 用户名 | `strong a.l` | 显示名称 |
| 评论文本 | `div.message` | `.get_text(strip=True)` |
| 时间戳 | `small a.floor-anchor` | 格式 `#N - YYYY-MM-DD HH:MM` |
| 楼层 | `small a.floor-anchor` | 提取 `#N` 部分 |

### 解析方式

```python
# scraper/bangumi.py

@dataclass
class Comment:
    username: str
    text: str
    timestamp: str
    floor: int

class BangumiScraper:
    """爬取 Bangumi 剧集页面评论"""

    def __init__(self, config: PluginConfig):
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[int, tuple[float, list[Comment]]] = {}
        self._cache_ttl: int = 86400  # 24h

    async def get_episode_comments(
        self, episode_id: int, limit: int = 20
    ) -> list[Comment]: ...
```

### 频率限制

- 爬取请求同样遵循 >= 0.5s 间隔（使用 `asyncio.sleep()`）
- 由于启用内存缓存（TTL 24h），同一集的评论**不会**重复请求

### 缓存策略

- **位置**：`BangumiScraper` 实例内存（dict）
- **Key**：`episode_id`
- **TTL**：默认 86400s（24h），可通过配置调整
- **依据**：已播出剧集的评论不再变化，24h TTL 安全且合理

### 容错

- 网络错误 / 解析失败 → 返回空列表，不影响主流程
- 访谈引擎检测到空评论列表时，降级为不使用评论上下文的普通问题
- HTML 结构变更 → 解析失败时记录 warning 日志并返回空列表

### 与 api/bangumi.py 的关系

`api/bangumi.py`（JSON REST API）和 `scraper/bangumi.py`（HTML 解析）是独立模块：

| | api/bangumi.py | scraper/bangumi.py |
|---|---|---|
| 数据格式 | JSON | HTML |
| 认证 | Bearer Token | 无需认证（公开页面） |
| 基础 URL | `https://api.bgm.tv` | `https://bgm.tv` |
| 用途 | 条目查询、收藏管理、进度同步 | 获取剧集评论上下文 |
| 速率限制 | search >= 1s, update >= 0.5s | >= 0.5s |
