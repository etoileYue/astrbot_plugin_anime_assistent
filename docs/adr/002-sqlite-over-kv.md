# ADR-002: 使用 SQLite 统一存储而非混用 AstrBot KV

## 背景

AstrBot 提供插件级别的 KV 存储 API（`put_kv_data` / `get_kv_data`）。需要决定运行时状态（Bangumi token、last_check_time 等）是存入 AstrBot KV 还是自己管理的 SQLite。

## 决策

全部数据统一存储在 SQLite 中，不使用 AstrBot 的 KV 存储。

## 原因

- **数据一致性**：所有插件数据在一个 SQLite 文件中，备份和迁移简单
- **关系查询**：`task_state` 表虽然目前只有 `last_check_time`，但后续可能扩展（如 per-user 状态、per-subscription 检查时间）。SQLite 比 KV 更容易处理这种扩展
- **事务支持**：状态更新可以和数据操作在同一事务中
- **减少外部依赖**：不需要依赖 AstrBot 的 KV 实现细节。如果用 KV，插件的状态和数据库数据分布在两个系统
- **调试便利**：单个 `.db` 文件可直接用 `sqlite3` CLI 检查，比调试 KV 存储方便

## 替代方案

| 方案 | 评估 |
|------|------|
| 混用 SQLite + AstrBot KV | 数据分散在两个系统，增加心智负担 |
| 纯 AstrBot KV | 不支持关系查询，不适合多表数据 |
| JSON 文件 | 并发写入不安全，不适合频繁更新 |

## 影响

- `task_state` 表承担了 KV 存储的职责（`key`/`value` 结构）
- Bangumi token 存储在 `users.bangumi_token` 字段，同时可通过 `_conf_schema.json` 配置全局默认值
- 插件完全自包含，不依赖 AstrBot 存储 API
