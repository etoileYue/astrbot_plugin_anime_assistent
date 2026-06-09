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
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**说明**：
- `last_notified_ep` 是更新检测的核心字段。定时任务获取最新集数后与此字段对比，若新集数更大则触发通知。
- `watched_eps` 记录已看集数，来源为 Bangumi API 返回的 `ep_status` 字段。插件初始化时自动同步，进度消息同步时也会更新。
- `subject_name` 是本地缓存，避免每次显示时都调 API。
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
    episode     INTEGER NOT NULL,
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
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**说明**：每条记录是一轮问答。一次访谈可能有多轮。Markdown 文件的生成以本表数据为源。

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
