# ADR-001: 使用 aiosqlite 作为 SQLite 驱动

## 背景

需要选择 Python SQLite 异步驱动。标准库 `sqlite3` 是同步的，会阻塞 AstrBot 的事件循环。

## 决策

使用 `aiosqlite`（基于 `sqlite3` 的异步包装）作为数据库驱动。

## 原因

- AstrBot 是基于 asyncio 的异步框架，所有 I/O 必须是非阻塞的
- `aiosqlite` 在线程池中执行实际的 SQLite 操作，对调用方暴露 async/await 接口
- 比 `sqlite3` + `run_in_executor` 模式更简洁
- 轻量级依赖，无外部服务依赖
- 社区活跃，与 aiohttp/httpx 等异步生态兼容

## 替代方案

| 方案 | 评估 |
|------|------|
| `sqlite3` (同步) | 会阻塞事件循环，不符合 AstrBot 要求 |
| `sqlite3` + `asyncio.to_thread` | 可行但增加样板代码，不如 aiosqlite 简洁 |
| `asyncpg` / `aiomysql` | 需要额外数据库服务，MVP 阶段过度设计 |
| AstrBot 内置 KV 存储 | 只适合简单 KV，不适合关系查询和多表关联 |

## 影响

- `requirements.txt` 增加 `aiosqlite>=0.20.0` 依赖
- 所有数据库操作使用 `await`
- 数据库文件位于 AstrBot 插件 data 目录下（通过 `context.get_data_path()` 获取绝对路径），具体为 `{data_path}/bangumi.db`
