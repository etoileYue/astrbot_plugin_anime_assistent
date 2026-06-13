# ADR-005: HTML 爬取作为独立 scraper/ 模块

## 背景

访谈功能需要获取 Bangumi 剧集评论作为 LLM 上下文，但 Bangumi API v0 不提供评论/讨论端点。剧集页面的「吐槽箱」（`https://bgm.tv/ep/{episode_id}`）包含用户评论，在服务端渲染到 HTML 中，可爬取解析。需要决定：将爬取代码放在现有的 `api/bangumi.py` 中，还是作为独立模块。

## 决策

创建独立的 `scraper/bangumi.py` 模块，与 `api/bangumi.py` 分离。

## 原因

- **不同数据格式**：API client 处理 JSON REST 响应，scraper 解析 HTML DOM。两者的请求构造、错误处理、数据提取方式完全不同
- **不同认证方式**：API 需要 Bearer Token 认证，HTML 页面是公开的（无需认证）
- **不同基础 URL**：API 使用 `https://api.bgm.tv`，HTML 页面使用 `https://bgm.tv`
- **不同稳定性预期**：REST API 有版本保证（v0），HTML 结构可能随网站更新而变化，需要独立维护
- **单一职责**：`api/bangumi.py` 已有 240+ 行，继续膨胀会降低可维护性
- **依赖不同**：scraper 引入 `beautifulsoup4` 依赖，不应强制与 API client 绑定

## 配套决策

### BeautifulSoup 4 作为 HTML 解析器

- 选择 `beautifulsoup4>=4.12.0`
- **原因**：社区标准，文档丰富，容错性好（能处理不规范的 HTML），与 httpx 配合简单
- **替代方案**：`selectolax`（更快但不够流行）、`lxml`（更底层）

### 内存 TTL 缓存

- 在 `BangumiScraper` 实例中使用 dict + `time.time()` 实现，TTL 默认 86400s（24h）
- **原因**：已播出剧集的评论不再变化，24h 足够避免重复请求；内存缓存简单无依赖，适合 MVP
- **不选择 DB 缓存**：评论数据量小，无需持久化到 SQLite
- **不选择 Redis**：MVP 阶段不引入外部服务

## 替代方案

| 方案 | 评估 |
|------|------|
| 将爬取方法添加到 `api/bangumi.py` | 职责混杂，API client 变得臃肿，HTML 解析逻辑与 JSON 处理混在一起 |
| 使用 Playwright/headless browser | 过于重量级，部署复杂，评论实际在服务端渲染无需 JS 执行 |
| 直接调用 Bangumi 内部 AJAX API | API 路径可能随时变化，无文档保证；HTML 结构同样无保证但解析方式更通用 |
| 不爬取，仅用 LLM 知识 | 当前方案的问题，LLM 无法知道该集的具体讨论点，问题空洞 |

## 影响

- 新增 `scraper/` 模块目录和 `beautifulsoup4` 依赖
- `InterviewEngine._generate_initial_question()` 在生成问题前调用 scraper 获取评论
- 爬取失败时降级为无评论上下文的普通问题生成，不阻塞访谈流程
- 模块分层：`scraper/` 位于 `api/`、`llm/` 同层的"数据采集层"
