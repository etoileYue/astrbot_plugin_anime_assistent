# SQLite 数据库设计

## 表结构总览

```
users ──┬── subscriptions ──┬── watch_log
        │                    │
        │                    └── interviews
        │
        └── (aliases 不直接关联 user，通过 subject_id 关联)
```

## 建表 SQL

### users — 用户配置

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY,
    qq_id       TEXT UNIQUE NOT NULL,        -- QQ号
    bangumi_token TEXT,                       -- Bangumi access token
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**说明**：当前 MVP 阶段只有你一个用户。设计上预留多用户支持。

### subscriptions — 追番列表

```sql
CREATE TABLE subscriptions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    subject_id  INTEGER NOT NULL,            -- Bangumi 条目ID
    subject_name TEXT NOT NULL,              -- 番剧中文名（本地缓存）
    subject_name_cn TEXT,                    -- Bangumi 中文名
    status      INTEGER DEFAULT 3,           -- 1=想看 2=看过 3=在看 4=搁置 5=抛弃
    total_eps   INTEGER,                     -- 总集数
    last_notified_ep INTEGER DEFAULT 0,      -- 最后一次通知的集数
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, subject_id)
);
```

**说明**：
- `last_notified_ep` 是更新检测的核心字段。定时任务获取最新集数后与此字段对比，若新集数更大则触发通知。
- `subject_name` 是本地缓存，避免每次显示时都调 API。
- `status` 值与 Bangumi 收藏类型一致。

### aliases — 番剧别名

```sql
CREATE TABLE aliases (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL,            -- Bangumi 条目ID
    alias       TEXT NOT NULL,               -- 别名（如"芙莉莲"、"葬送的芙莉莲"）
    UNIQUE(subject_id, alias)
);
```

**说明**：
- 这是消息解析的核心——用户发送"芙莉莲15看完"时，通过别名匹配到正确的 `subject_id`。
- 初始数据需要手动导入（常用简称/昵称）。
- 后续可通过 Bangumi 搜索 API 自动补全别名。

### watch_log — 观看记录

```sql
CREATE TABLE watch_log (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    watched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source      TEXT DEFAULT 'manual'        -- 'manual' = QQ消息同步, 'bangumi_sync' = 从Bangumi同步
);
```

**说明**：记录每次观看行为，用于后续统计（季度总结、观看频率等）。

### interviews — 访谈记录

```sql
CREATE TABLE interviews (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    subject_id  INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    question    TEXT NOT NULL,               -- AI提出的问题
    answer      TEXT,                        -- 用户回答（可能为空，等待回答中）
    round       INTEGER DEFAULT 1,           -- 第几轮对话
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**说明**：每条记录是一轮问答。一次访谈可能有多轮。Markdown 文件的生成以本表数据为源。

### task_state — 定时任务状态

```sql
CREATE TABLE task_state (
    key         TEXT PRIMARY KEY,            -- 如 'last_check_time'
    value       TEXT NOT NULL
);
```

**说明**：简单的 KV 表，存储调度器的运行状态。当前主要存 `last_check_time`。

## ER 图

```
┌──────────┐       ┌──────────────────┐       ┌─────────────┐
│  users   │       │  subscriptions   │       │   aliases   │
├──────────┤       ├──────────────────┤       ├─────────────┤
│ id (PK)  │───┐   │ id (PK)          │   ┌──│ subject_id   │
│ qq_id    │   └──▶│ user_id (FK)     │   │  │ alias        │
│ token    │       │ subject_id       │◀──┤  └─────────────┘
└──────────┘       │ subject_name     │   │
                   │ status           │   │  ┌─────────────┐
                   │ total_eps        │   │  │  watch_log  │
                   │ last_notified_ep │   │  ├─────────────┤
                   └────────┬─────────┘   │  │ id (PK)     │
                            │             │  │ user_id (FK)│
                            │             └──│ subject_id  │
                            │                │ episode     │
                            │                │ watched_at  │
                            │                └─────────────┘
                            │
                            │           ┌──────────────┐
                            │           │  interviews  │
                            │           ├──────────────┤
                            └──────────▶│ id (PK)      │
                                        │ user_id (FK) │
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

## MVP 阶段初始化数据

```sql
-- 插入你自己
INSERT INTO users (qq_id) VALUES ('你的QQ号');

-- 手动导入追番列表中的番剧别名
INSERT INTO aliases (subject_id, alias) VALUES
  (400602, '芙莉莲'),
  (400602, '葬送的芙莉莲'),
  (400602, 'frieren'),
  -- ... 其他番剧
;
```
