# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

BangumiBot — 基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 框架的追番管理插件。通过 QQ 机器人管理 Bangumi 追番列表、同步观看进度、LLM 驱动的观感访谈、自动生成 Obsidian 兼容的 Markdown 观感记录。

- **Bot 框架**: AstrBot >= 4.16（Docker 部署，镜像 `soulter/astrbot:latest`）
- **语言**: Python 3.12+，HTTP 客户端使用 httpx（异步，禁止同步 `requests`）
- **数据库**: SQLite
- **外部 API**: Bangumi API v0（Personal Access Token 认证，base URL `https://api.bgm.tv`）
- **LLM**: 可替换 provider（OpenAI / Claude / Gemini / DeepSeek）

## 目录结构

```
├── main.py              # 插件入口（当前为 helloworld 模板）
├── metadata.yaml         # AstrBot 插件元信息
├── docs/                 # 完整设计文档（见下）
```

## 文档导航

当需要了解以下内容时，查阅对应文档：

| 场景 | 文件 |
|------|------|
| 理解系统架构、组件关系、部署拓扑 | `docs/architecture.md` |
| 查看开发阶段、当前进度、各阶段任务 | `docs/development-plan.md` |
| 了解模块目录结构和职责划分 | `docs/modules.md` |
| 设计或修改 SQLite 表结构 | `docs/database.md` |
| 封装、调用或调试 Bangumi API | `docs/bangumi-api.md` |
| 理解某功能的数据流转（提醒/同步/访谈/保存） | `docs/data-flow.md` |
| 了解观感记录 Markdown 文件格式和存储策略 | `docs/markdown-storage.md` |
| 配置 QQ 机器人、AstrBot 连接、NapCat 扩展 | `docs/qqbot-astrbot.md` |
| AstrBot 插件 API（命令注册、事件处理等） | https://docs.astrbot.app/dev/star/plugin-new.html |
| Bangumi API 参考 | https://github.com/bangumi/api |

## ADR
重要架构决策必须记录到 docs/adr/。

每个 ADR 应说明：背景, 决策, 原因, 替代方案, 影响

后续开发优先遵循 ADR；决策变更时新增 ADR，而非修改历史记录。

## 关键约束

- 所有网络请求用 httpx 异步，禁止同步阻塞
- Bangumi API 频率限制：搜索 >= 1s，更新 >= 0.5s
- Bangumi 章节 ID ≠ 集数，须通过 API 获取映射
- 更新 Bangumi 进度前必须先收藏条目，否则 400
- Access Token 为个人令牌，不会自动过期；如遇 401 需重新获取
- 消息路由优先级：命令 → 进度同步模式 → 访谈会话 → 默认 LLM
- 回复使用中文
