# 数据流设计

## 0. Bangumi 收藏同步（插件初始化 / 手动触发）

```
Plugin initialize() 或用户执行 /sub sync
  │
  ├─ 1. 调 Bangumi API GET /v0/users/-/collections?type=3&limit=50&offset=0
  │     分页获取所有「在看」收藏（token 自动标识用户）
  ├─ 2. 对每个收藏条目：
  │     ├─ INSERT OR IGNORE INTO subscriptions（不覆盖已有记录）
  │     └─ INSERT OR IGNORE INTO aliases（name, name_cn, subject_id）
  ├─ 3. commit
  └─ 4. 返回统计：总数 / 新增数
```

**注意**：
- last_notified_ep 初始化为 0，由下次定时更新检查自动填充
- 使用 INSERT OR IGNORE 避免覆盖用户手动添加的订阅
- 同步失败不阻塞插件启动

## 1. 番剧更新提醒（定时触发）

```
Scheduler (每N小时触发)
  │
  ├─ 1. 从 task_state 读取 last_check_time
  ├─ 2. 从 subscriptions 读取所有 status=3（在看）的条目
  ├─ 3. 对每个条目：
  │     ├─ 调 Bangumi API GET /v0/users/-/collections/{subject_id}
  │     │   获取用户收藏状态（含当前进度 ep_status）
  │     └─ 调 Bangumi API GET /v0/episodes?subject_id={subject_id}
  │         获取最新集数
  ├─ 4. 比较 new_ep > subscriptions.last_notified_ep
  ├─ 5. 若有更新：
  │     ├─ 构造通知消息
  │     ├─ 通过 AstrBot 发 QQ 消息给用户
  │     └─ 更新 subscriptions.last_notified_ep = new_ep
  └─ 6. 更新 task_state.last_check_time
```

**通知消息格式：**

```
【番剧更新提醒】
葬送的芙莉莲
第16集已更新
```

## 2. 同步观看进度（用户消息触发）

```
用户消息: "芙莉莲15看完"
  │
  ├─ 1. AstrBot 将消息路由到 progress handler
  │     （通过 @filter.command 或自定义事件监听）
  │
  ├─ 2. 消息解析：
  │     ├─ 正则提取：番剧名片段 + 数字
  │     ├─ 模式匹配："{name}{num}看完" / "{name}看到{num}" 等
  │     └─ 得到：alias="芙莉莲", episode=15
  │
  ├─ 3. 别名匹配：
  │     ├─ 在 aliases 表中查 alias="芙莉莲"
  │     ├─ 得到 subject_id=400602
  │     └─ 若未匹配：调 Bangumi 搜索 API，让用户选择
  │
  ├─ 4. 查 subscriptions：
  │     ├─ 若未订阅 → 自动添加到追番列表
  │     └─ 若已订阅 → 检查是否在追番列表中
  │
  ├─ 5. 更新 Bangumi：
  │     ├─ GET /v0/users/-/collections/{subject_id}
  │     │   确认条目已收藏
  │     ├─ 若未收藏 → POST /v0/users/-/collections/{subject_id}
  │     │   添加到收藏（status=3 在看）
  │     ├─ GET /v0/episodes?subject_id={subject_id}
  │     │   获取章节列表，找到 ep=15 对应的 episode_id
  │     └─ PUT /v0/users/-/collections/-/episodes/{episode_id}
  │         标记第15集为"看过"
  │
  ├─ 6. 更新本地数据库：
  │     ├─ INSERT INTO watch_log (subject_id, episode, source='manual')
  │     └─ UPDATE subscriptions SET last_notified_ep = MAX(last_notified_ep, 15)
  │
  └─ 7. 返回确认消息：
       【已同步 Bangumi】
       葬送的芙莉莲
       观看进度：15/28
```

## 3. 观感访谈（同步完成后触发）

```
同步进度完成
  │
  ├─ 1. 访谈引擎初始化：
  │     ├─ 创建访谈会话（subject_id + episode + user_id）
  │     └─ 状态 = "等待发起"
  │
  ├─ 2. 获取该集评论上下文：
  │     ├─ 通过 Bangumi API GET /v0/episodes?subject_id={subject_id}
  │     │   获取章节列表，找到 ep={episode} 对应的 episode_id
  │     ├─ 查 scraper 缓存（key=episode_id, TTL=86400s）
  │     ├─ 缓存未命中 → 爬取 https://bgm.tv/ep/{episode_id}
  │     │   （使用 scraper/bangumi.py，>= 0.5s rate limit）
  │     ├─ 解析 HTML（div#comment_list → BeautifulSoup → [Comment])
  │     ├─ 写入缓存
  │     └─ 格式化为评论文本（取前 N 条）
  │
  ├─ 3. 生成初始问题：
  │     ├─ 调 LLM，prompt 包含：
  │     │   - 番剧名称和集数
  │     │   - Bangumi 真实用户评论（如获取成功）
  │     │   - 指令：基于真实评论中的讨论点生成开放式问题
  │     └─ 得到问题文本
  │
  ├─ 4. 发送问题到 QQ
  │
  ├─ 5. 用户回复：
  │     ├─ interview handler 接收消息
  │     ├─ 识别为访谈回复（通过会话状态判断）
  │     ├─ 存入 interviews 表
  │     └─ 调 LLM 分析回答，生成追问
  │
  ├─ 6. 追问循环（2-3轮）：
  │     ├─ 每轮：LLM 生成追问 → 用户回答 → 存入 DB
  │     └─ 结束条件：用户说"不聊了" / 达到最大轮数 / LLM 判断可结束
  │
  └─ 7. 访谈结束：
        └─ 触发 Markdown 保存（见下一条）
```

## 4. 观感记录保存（访谈结束后触发）

```
访谈结束
  │
  ├─ 1. 从 interviews 表读取本次访谈的所有问答
  │
  ├─ 2. 构造 Markdown 内容：
  │     ├─ YAML frontmatter（anime, episode, title, watched_at, subject_id）
  │     ├─ 标题
  │     └─ Q&A 对话
  │
  ├─ 3. 目录和文件命名：
  │     ├─ 目录：anime_notes/{subject_name}/
  │     └─ 文件：ep{episode:02d}.md
  │
  └─ 4. 写入文件
```

## 状态流转图（访谈）

```
        同步进度完成
             │
             ▼
      ┌──────────────┐
      │  获取集评论    │
      │  (爬取/缓存)   │
      └──────┬───────┘
             ▼
      ┌──────────────┐
      │  生成初始问题  │
      └──────┬───────┘
             │ 发送问题
             ▼
      ┌──────────────┐
      │  等待用户回答  │◀──────────────┐
      └──────┬───────┘                │
             │ 收到回答                │
             ▼                        │
      ┌──────────────┐                │
      │  分析回答     │                │
      │  生成追问     │────────────────┘
      └──────┬───────┘   (继续追问)
             │
             │ (判断可以结束)
             ▼
      ┌──────────────┐
      │  保存记录     │
      │  结束访谈     │
      └──────────────┘
```

## 消息识别流程

用户发送消息后，需要判断消息的意图：

```
收到 QQ 消息
  │
  ├─ 匹配 AstrBot 命令（如 /sub list）──▶ 命令处理器
  │
  ├─ 匹配进度同步模式（如"芙莉莲15看完"）──▶ progress handler
  │
  ├─ 当前有活跃访谈会话 ──▶ interview handler
  │
  └─ 都不匹配 ──▶ 交给 AstrBot 默认 LLM 处理（或者忽略）
```

**进度同步的匹配优先级**：先精确匹配命令，再尝试模式匹配。这样可以避免把普通聊天误识别为进度同步。
