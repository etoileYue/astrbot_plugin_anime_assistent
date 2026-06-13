# 开发阶段规划

## 总览

| Phase | 名称 | 预计时间 | 核心产出 |
|-------|------|---------|---------|
| 0 | 环境搭建 | 1-2 天 | AstrBot + QQ 官方机器人跑通 |
| 1 | Bangumi API 集成 | 2-3 天 | 搜索、查询、更新能力 |
| 2 | 番剧更新提醒 | 2-3 天 | 定时检查 + QQ 通知 |
| 3 | 观看进度同步 | 2-3 天 | 消息解析 + 自动同步 |
| 4 | 观感访谈 | 3-4 天 | LLM 驱动的多轮对话 |
| 5 | Markdown 记录 | 1-2 天 | 观感文件保存 |

**MVP = Phase 0-3，预计 7-11 天**

---

## Phase 0：环境搭建

**目标**：AstrBot + QQ 官方机器人跑通，插件能响应 QQ 消息。

### 步骤

| # | 任务 | 细节 |
|---|------|------|
| 0.1 | 注册 QQ 开放平台应用 | 在 q.qq.com 创建机器人，获取 AppID / AppSecret / Token |
| 0.2 | Docker 环境确认 | 确认 Docker 和 Docker Compose 可用 |
| 0.3 | 部署 AstrBot | Docker Compose 启动 AstrBot 容器 |
| 0.4 | 配置 QQ 官方适配器 | AstrBot WebUI (6185) 中添加 QQ 官方机器人适配器 |
| 0.5 | 配置 LLM | AstrBot WebUI 中配置 DeepSeek 或其他 LLM |
| 0.6 | 验证对话 | QQ 上发消息给机器人，确认能收到回复 |
| 0.7 | 创建插件骨架 | 基于 helloworld 模板创建 `astrbot_plugin_bangumi` |
| 0.8 | 验证插件 | `/helloworld` 命令在 QQ 上跑通 |

### 验证标准

在 QQ 上对机器人发送命令，收到正确的插件回复。

---

## Phase 1：Bangumi API 集成

**目标**：插件能搜索番剧、查询收藏、更新进度。

### 步骤

| # | 任务 | 细节 |
|---|------|------|
| 1.1 | 配置 Bangumi Token | 从 https://next.bgm.tv/demo/access-token 获取个人 Access Token |
| 1.2 | 实现 Bearer Token 认证 | 将 Token 注入 HTTP 请求头 |
| 1.3 | 实现 `api/bangumi.py` | search_subject, get_subject, get_episodes |
| 1.4 | 实现收藏操作 | get_collection, add_collection, update_collection |
| 1.5 | 实现进度操作 | mark_episode_watched, batch_update_episodes |
| 1.6 | 实现 SQLite 初始化 | 创建所有表，数据库连接管理 |
| 1.7 | 实现配置管理 | Bangumi token 存取到 AstrBot 插件配置 |
| 1.8 | 实现 `/search` 命令 | QQ 上发 `/search 芙莉莲`，返回搜索结果 |

### 验证标准

通过插件命令 `/search 芙莉莲` 返回 Bangumi 搜索结果，能查看收藏状态。

---

## Phase 2：番剧更新提醒

**目标**：定时检查更新，自动发送 QQ 通知。

### 步骤

| # | 任务 | 细节 |
|---|------|------|
| 2.1 | 实现追番列表管理 | `/sub add/list/remove` 命令 |
| 2.2 | 实现别名管理 | 订阅时自动/手动添加别名 |
| 2.3 | 实现 `core/scheduler.py` | 定时轮询逻辑 |
| 2.4 | 实现更新检测 | 对比最新集数与 last_notified_ep |
| 2.5 | 实现通知发送 | 构造通知消息并通过 AstrBot 发送 |
| 2.6 | 注册定时任务 | 在 AstrBot 中注册定时回调 |

### 验证标准

订阅一部正在更新的番剧，等到更新日，自动收到 QQ 通知。

---

## Phase 3：观看进度同步

**目标**：发送消息自动同步观看进度到 Bangumi。

### 步骤

| # | 任务 | 细节 |
|---|------|------|
| 3.1 | 实现消息解析器 | 正则提取番剧名和集数 |
| 3.2 | 实现别名匹配 | 在 aliases 表中查找 |
| 3.3 | 实现模糊匹配兜底 | 匹配失败时调用搜索 API |
| 3.4 | 实现 Bangumi 进度更新 | 调用 API 更新集数状态 |
| 3.5 | 实现确认回复 | 格式化返回同步结果 |
| 3.6 | 实现 watch_log 记录 | 本地记录观看历史 |
| 3.7 | 填充初始别名数据 | 手动导入你追的番剧的别名 |

### 验证标准

发送"芙莉莲15看完"，Bangumi 上观看进度更新为 15/28，收到确认回复。

---

## Phase 4：观感访谈

**目标**：同步进度后自动发起多轮访谈对话。

### 步骤

| # | 任务 | 细节 |
|---|------|------|
| 4.1 | 实现 `llm/client.py` | 统一 LLM 调用接口 |
| 4.2 | 设计访谈 prompt | 问题生成的 system prompt |
| 4.3 | 实现剧集评论爬取 | 爬取 Bangumi 剧集页面评论，注入 LLM prompt |
| 4.4 | 实现访谈状态机 | 管理对话状态流转 |
| 4.5 | 实现初始问题生成 | 基于番剧信息和评论上下文生成第一个问题 |
| 4.6 | 实现追问生成 | 基于用户回答生成追问 |
| 4.7 | 实现结束判断 | 用户主动结束 / 达到最大轮数 |
| 4.8 | 实现会话识别 | 区分访谈消息和普通消息 |

### 4.3 剧集评论爬取

**目标**：从 Bangumi 剧集页面爬取真实用户评论，为访谈引擎提供上下文，生成更具体的问题。

| # | 子任务 | 细节 |
|---|--------|------|
| 4.3.1 | 添加依赖 | 将 `beautifulsoup4>=4.12.0` 加入 `requirements.txt` |
| 4.3.2 | 创建 `scraper/` 包 | 创建 `scraper/__init__.py` 和 `scraper/bangumi.py` |
| 4.3.3 | 实现 `Comment` 数据类 | dataclass: username, text, timestamp, floor |
| 4.3.4 | 实现 `BangumiScraper` | 封装 httpx.AsyncClient + 速率限制 |
| 4.3.5 | 实现 HTML 解析 | 使用 BeautifulSoup 解析 `#comment_list div.row_reply` |
| 4.3.6 | 实现内存 TTL 缓存 | dict + time.time()，TTL 可配置（默认 86400s） |
| 4.3.7 | 实现公共接口 | `async def get_episode_comments(episode_id, limit=20) -> list[Comment]` |
| 4.3.8 | 集成到 `InterviewEngine` | 在 `_generate_initial_question()` 中调用 scraper，将评论注入 LLM prompt |
| 4.3.9 | 更新 LLM prompt | 将评论作为上下文传入，指令 LLM 基于评论中的讨论点提问 |
| 4.3.10 | 容错处理 | 爬取失败时降级为无评论上下文的普通问题 |

**验证标准**：
- 能通过 episode_id 获取真实剧集评论
- 评论被正确解析为结构化数据
- 缓存命中时不再发起 HTTP 请求
- LLM 生成的问题引用了剧集中的具体情节或评论中的讨论点
- 爬取失败时不影响访谈主流程

### 验证标准

同步进度后，机器人主动问问题（基于真实用户评论），问题具体有深度。用户回答后，机器人能追问。说"不聊了"后结束。

---

## Phase 5：Markdown 记录

**目标**：访谈内容自动保存为 Obsidian 兼容的 Markdown 文件。

### 步骤

| # | 任务 | 细节 |
|---|------|------|
| 5.1 | 实现 `storage/markdown.py` | Markdown 文件读写 |
| 5.2 | 实现 YAML frontmatter | 结构化的元数据头 |
| 5.3 | 实现目录管理 | 自动创建番剧子目录 |
| 5.4 | 实现标签提取 | LLM 从对话中提取关键词 |
| 5.5 | 集成到访谈结束流程 | 访谈结束时自动保存 |
| 5.6 | 实现 `/notes list` | 查看已有观感记录 |

### 验证标准

完成访谈后，`anime_notes/` 下生成格式正确的 Markdown 文件，可在 Obsidian 中打开。

---

## Phase 6：后续扩展（远期）

- **季度追番总结**：统计观看数量、最常讨论主题、关键词云
- **完结自动生成长评**：汇总所有集数观感，LLM 生成完整观后感
- **AniList / TMDB 集成**：扩展数据源
- **WebUI 仪表盘**：可视化追番进度和统计
- **多用户支持**：支持多人各自管理追番列表
