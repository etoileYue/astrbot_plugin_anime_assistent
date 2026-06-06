# 模块划分

## 目录结构

```
astrbot_plugin_bangumi_assistent/
│
├── metadata.yaml              # 插件元信息
├── main.py                    # 插件入口，Star 类，注册命令/事件
├── requirements.txt           # 依赖声明
│
├── core/                      # 核心业务逻辑
│   ├── __init__.py
│   ├── config.py              # 配置管理（读取/写入插件配置）
│   ├── scheduler.py           # 定时任务（检查番剧更新）
│   └── interview_engine.py    # 访谈引擎（生成问题、管理会话状态）
│
├── api/                       # 外部 API 封装
│   ├── __init__.py
│   └── bangumi.py             # Bangumi API 客户端
│
├── llm/                       # LLM 调用封装
│   ├── __init__.py
│   └── client.py              # 可替换的 LLM 客户端
│
├── storage/                   # 数据持久化
│   ├── __init__.py
│   ├── database.py            # SQLite 操作
│   ├── models.py              # 数据模型定义
│   └── markdown.py            # Markdown 文件读写
│
└── handlers/                  # 消息/事件处理器
    ├── __init__.py
    ├── progress.py            # 处理"芙莉莲15看完"类消息
    ├── subscription.py        # 管理追番列表
    └── interview.py           # 访谈对话处理
```

## 各模块职责

### main.py — 插件入口

- 继承 `Star` 类
- 注册所有命令和事件处理器
- 初始化调度器
- 负责将消息路由到对应的 handler

**依赖**：所有 handler 模块

### core/config.py — 配置管理

- 从 AstrBot 插件配置系统读取配置
- 配置项：Bangumi OAuth2 token、LLM API key、检查间隔、通知方式等
- 提供配置的读取和写入接口

**依赖**：无

### core/scheduler.py — 定时调度器

- 定时轮询 Bangumi 检查番剧更新
- 与本地数据库对比，发现新集数后触发通知
- 使用 AstrBot 的定时任务机制

**依赖**：`api/bangumi.py`, `storage/database.py`

### core/interview_engine.py — 访谈引擎

- 管理访谈状态机（发起提问 → 等待回答 → 追问 → 结束）
- 基于当前番剧/集数上下文生成初始问题
- 根据用户回答生成追问
- 判断访谈结束条件

**依赖**：`llm/client.py`

### api/bangumi.py — Bangumi API 客户端

- 封装 Bangumi API v0 的所有接口
- 处理 OAuth2 认证
- 处理请求频率限制
- 数据格式转换（API 响应 → 内部数据结构）

**依赖**：无（仅依赖 httpx）

### llm/client.py — LLM 客户端

- 统一的 LLM 调用接口
- 支持多 provider（OpenAI / Claude / Gemini / DeepSeek）
- 通过配置切换 provider

**依赖**：无（仅依赖各 LLM SDK 或 httpx）

### storage/database.py — 数据库操作

- SQLite 数据库初始化（建表）
- 所有 CRUD 操作
- 数据库迁移（如果后续需要）

**依赖**：`storage/models.py`

### storage/models.py — 数据模型

- 定义数据类（dataclass），对应数据库表结构
- 纯数据结构，不含业务逻辑

**依赖**：无

### storage/markdown.py — Markdown 存储

- 观感记录的读写
- 生成 Obsidian 兼容的 YAML frontmatter
- 目录和文件命名管理

**依赖**：无

### handlers/progress.py — 进度同步处理器

- 解析用户消息（提取番剧名和集数）
- 通过别名表匹配 Bangumi 条目
- 调用 Bangumi API 更新观看进度
- 返回确认消息

**依赖**：`api/bangumi.py`, `storage/database.py`

### handlers/subscription.py — 追番管理处理器

- 追番列表的查询、添加、删除
- 别名管理

**依赖**：`api/bangumi.py`, `storage/database.py`

### handlers/interview.py — 访谈处理器

- 访谈消息的接收和分发
- 调用访谈引擎处理用户回答
- 触发 Markdown 保存

**依赖**：`core/interview_engine.py`, `storage/markdown.py`

## 模块分层

```
┌─────────────────────────────────┐
│          main.py                │  ← 入口层：命令注册、事件路由
├─────────────────────────────────┤
│         handlers/               │  ← 处理层：消息解析、流程控制
├─────────────────────────────────┤
│           core/                 │  ← 业务层：调度、访谈引擎
├──────────────────┬──────────────┤
│     api/         │    llm/      │  ← 外部接口层：API 封装
├──────────────────┴──────────────┤
│          storage/               │  ← 持久层：数据库、文件
└─────────────────────────────────┘
```

上层可以依赖下层，下层不依赖上层。

## 设计原则

1. **单插件承载所有功能** — MVP 阶段不需要多插件复杂度
2. **模块间通过明确的接口通信** — 每个模块只暴露必要的公共方法
3. **下层不依赖上层** — storage 不知道 handler 的存在
4. **LLM 可替换** — `llm/client.py` 提供统一接口，切换 provider 只需改配置
5. **先跑通再优化** — 初期不必追求完美的抽象
