# SQLite 数据库设计

## 表结构总览

```
subscriptions ──┬── watch_log
                │
                └── interviews

aliases（通过 subject_id 关联 subscriptions）

task_state（独立 KV 表）
```

## 建表 SQL

### subscriptions — 追番列表

```sql
CREATE TABLE subscriptions (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL UNIQUE,       -- Bangumi 条目ID
    subject_name TEXT NOT NULL,                -- 番剧名（本地缓存）
    subject_name_cn TEXT,                      -- Bangumi 中文名
    status      INTEGER DEFAULT 3,             -- 1=想看 2=看过 3=在看 4=搁置 5=抛弃
    total_eps   INTEGER,                       -- 总集数
    last_notified_ep INTEGER DEFAULT 0,        -- 最后一次通知的集数
    watched_eps INTEGER DEFAULT 0,             -- 已看集数（来源：Bangumi ep_status）
    airing      INTEGER DEFAULT 1,             -- Tenrai 确认仍在连载=1；已完结、提醒自动停用=0
    cover_url   TEXT,                          -- 列表卡封面 URL 缓存（可空）
    mal_id      INTEGER,                       -- Tenrai 严格匹配后的 MAL 条目 ID
    schedule_weekday INTEGER,                  -- 北京时间星期，周一=0 至周日=6
    schedule_time TEXT,                        -- 北京时间 HH:MM
    schedule_timezone TEXT,                    -- 有效排期固定为 Asia/Shanghai
    schedule_source TEXT,                      -- 'mal' 自动匹配，'manual' 手动/关闭
    last_schedule_notified_at TEXT,            -- 本周已提醒的播出时刻 ISO 时间
    schedule_checked INTEGER DEFAULT 0,        -- 是否已完成一次自动查询
    schedule_checked_at TEXT,                  -- 最近一次自动查询时间
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**说明**：
- 更新提醒由 `schedule_weekday`、`schedule_time` 与 `airing=1` 共同驱动，所有有效值均为北京时间；调度器以 `last_schedule_notified_at` 保证同一周只提醒一次。
- Tenrai 严格匹配结果的 `airing=false` 会写入 `airing=0` 并自动停用提醒；`airing=0` 的条目不再参与后续排期扫描。追番列表只以 `🔄` 标记仍在连载的条目，不为已完结条目追加提醒状态文字。
- `schedule_source='manual'` 且没有时间表示用户已明确关闭提醒，不会被自动补齐覆盖。手动有效排期仍会同步 Tenrai 的 `airing` 生命周期，但其星期和时间不会被改写。
- `last_notified_ep` 仅为兼容已有数据保留，不参与更新提醒判断。
- `watched_eps` 记录已看集数，来源为 Bangumi API 返回的 `ep_status` 字段。插件初始化时自动同步，进度消息同步时也会更新。
- `subject_name` 是本地缓存，避免每次显示时都调 API。
- `cover_url` 只缓存 Bangumi `images` 中按 `large → common → medium` 选出的 URL，不把图片二进制写入 SQLite。添加和收藏同步会刷新非空 URL；响应缺图时保留已有缓存。旧记录首次查看列表时按最多 4 个并发请求补齐，单项失败不影响其他条目。
- `status` 值与 Bangumi 收藏类型一致。
- 插件初始化时自动从 Bangumi 同步「在看」列表，也可通过 `/sub sync` 手动同步。

### aliases — 番剧别名

```sql
CREATE TABLE aliases (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,              -- Bangumi 条目ID
    alias       TEXT NOT NULL,                 -- 别名（如"芙莉莲"、"葬送的芙莉莲"）
    UNIQUE(subject_id, alias)
);
```

**说明**：
- 消息解析的核心——用户发送"芙莉莲15看完"时，通过别名匹配到正确的 `subject_id`。
- 同步和添加订阅时自动填充 name、name_cn、subject_id 作为别名。

### watch_log — 观看记录

```sql
CREATE TABLE watch_log (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,              -- 访谈范围终点
    watched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source      TEXT DEFAULT 'manual'          -- 'manual' = QQ消息同步, 'bangumi_sync' = 从Bangumi同步
);
```

**说明**：记录每次观看行为，用于后续统计（季度总结、观看频率等）。

### interviews — 访谈记录

```sql
CREATE TABLE interviews (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    question    TEXT NOT NULL,                 -- AI提出的问题
    answer      TEXT,                          -- 用户回答（可能为空，等待回答中）
    round       INTEGER DEFAULT 1,            -- 第几轮对话
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    episode_start INTEGER                     -- 访谈范围起点；单集时等于 episode
);
```

**说明**：每条记录是一轮问答。一次访谈可能有多轮；连续多集的合并访谈以
`episode_start` 至 `episode` 标识覆盖范围。活跃会话因后续观看进度扩展时，
该会话已写入的记录会按主键同步更新范围；历史会话不受影响。历史单集记录会
迁移为起止相同。

### task_state — 定时任务状态

```sql
CREATE TABLE task_state (
    key         TEXT PRIMARY KEY,              -- 如 'last_check_time'
    value       TEXT NOT NULL
);
```

**说明**：简单的 KV 表，存储调度器的运行状态。当前主要存 `last_check_time`。

## ER 图

```
┌──────────────────┐       ┌─────────────┐
│  subscriptions   │       │   aliases   │
├──────────────────┤       ├─────────────┤
│ id (PK)          │   ┌──│ subject_id   │
│ subject_id (UNQ) │◀──┤  │ alias        │
│ subject_name     │   │  └─────────────┘
│ cover_url        │   │
│ status           │   │
│ total_eps        │   │  ┌─────────────┐
│ last_notified_ep │   │  │  watch_log  │
└────────┬─────────┘   │  ├─────────────┘
         │             │  │ id (PK)     │
         │             └──│ subject_id  │
         │                │ episode     │
         │                │ watched_at  │
         │                │ source      │
         │                └─────────────┘
         │
         │           ┌──────────────┐
         │           │  interviews  │
         │           ├──────────────┤
         └──────────▶│ id (PK)      │
                     │ subject_id   │
                     │ episode      │
                     │ episode_start│
                     │ question     │
                     │ answer       │
                     │ round        │
                     └──────────────┘

                   ┌──────────────┐
                   │  task_state  │
                   ├──────────────┤
                   │ key (PK)     │
                   │ value        │
                   └──────────────┘
```
