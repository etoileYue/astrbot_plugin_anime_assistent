# ADR-004: 使用 asyncio.create_task 实现定时调度

## 背景

需要定时轮询 Bangumi API 检查番剧更新并推送 QQ 通知。AstrBot 框架没有内置的插件调度器 API。

## 决策

使用 `asyncio.create_task()` 启动后台循环，配合 `asyncio.sleep()` 实现定时调度。

## 原因

- **AstrBot 官方模式**：AstrBot 文档推荐的标准做法，社区插件普遍使用
- **简单可控**：启动/停止逻辑清晰（`run()` / `stop()`），无需引入第三方调度库
- **无需额外依赖**：Python 标准库即可实现
- **与 AstrBot 生命周期一致**：task 在 `initialize()` 中创建，在 `terminate()` 中取消

## 替代方案

| 方案 | 评估 |
|------|------|
| APScheduler | 功能丰富但引入重依赖，MVP 阶段过度设计 |
| `astrbot_plugin_sy`（第三方定时插件） | 增加部署复杂度，功能受限于第三方插件 |
| AstrBot Proactive Agent | 依赖 LLM 进行自然语言调度，不适合精确轮询 |
| `asyncio.TimerHandle` | 底层 API，不如 `create_task` + `sleep` 直观 |

## 影响

- `core/scheduler.py` 中的 `UpdateScheduler` 在单独的 asyncio task 中运行
- 检查间隔由 `_conf_schema.json` 中的 `check_interval_hours` 配置
- 主动推送通知需要预先存储 `unified_msg_origin`（通过用户首次交互时注册）
- 插件卸载时通过 `terminate()` 取消 task
