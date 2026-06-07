# BangumiBot 架构设计

## 系统架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         你的手机 / PC                             │
│  ┌──────┐    ┌──────────────────┐    ┌──────────────┐            │
│  │  QQ  │───▶│  QQ 官方机器人     │───▶│   AstrBot    │            │
│  │ 客户端 │    │  (QQ Bot API)    │    │  (Bot 框架)   │            │
│  └──────┘    │ Webhook/WebSocket│    │ 端口 6185     │            │
│              └──────────────────┘    └──────┬───────┘            │
│                                             │                    │
│                              ┌──────────────┴──────────┐         │
│                              │  bangumi_plugin         │         │
│                              │  ┌──────────────┐       │         │
│                              │  │ 消息处理器     │       │         │
│                              │  │ 定时调度器     │       │         │
│                              │  │ 访谈引擎      │       │         │
│                              │  │ LLM 客户端    │       │         │
│                              │  └──────┬───────┘       │         │
│                              └─────────┼───────────────┘         │
│                                        │                         │
│                    ┌───────────────────┼───────────────────┐     │
│                    │                   │                   │     │
│               ┌────▼────┐      ┌──────▼──────┐     ┌──────▼──┐  │
│               │ SQLite   │      │  Bangumi    │     │ Markdown│  │
│               │ (本地DB)  │      │  API (远程)  │     │ 文件存储 │  │
│               └─────────┘      └─────────────┘     └─────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## 关键路径

| 路径 | 说明 |
|------|------|
| QQ → QQ Bot | QQ 官方机器人接收/发送消息，通过 QQ Bot API 通信 |
| QQ Bot → AstrBot | Webhook / WebSocket，消息格式为 QQ Bot API 标准格式 |
| AstrBot → Plugin | AstrBot 将消息封装为 `AstrMessageEvent`，分发给各插件 |
| Plugin → Bangumi API | 插件通过 HTTP 调用 Bangumi API（Personal Access Token 认证） |
| Plugin → SQLite | 插件本地读写用户数据、追番列表、状态 |
| Plugin → Markdown | 插件写入观感记录到本地文件系统 |

## 组件说明

### QQ 官方机器人（QQ 接入层）

- **职责**：接收消息、发送消息
- **协议**：QQ Bot API，通过 Webhook 或 WebSocket 连接 AstrBot
- **配置**：在 QQ 开放平台注册应用，获取 AppID / AppSecret / Token
- **说明**：无需额外部署中间件，AstrBot 内置适配器直接对接

### AstrBot（Bot 框架）

- **职责**：插件管理、会话管理、定时任务、LLM 调用、MCP 支持
- **版本**：>= 4.16（支持最新 Star 插件系统）
- **部署**：Docker，镜像 `soulter/astrbot:latest`
- **WebUI**：端口 6185
- **WebSocket**：端口 6199（供 OneBot v11 适配器使用，如 NapCat 扩展方案）

### bangumi_plugin（追番插件）

- **职责**：所有追番业务逻辑
- **形式**：AstrBot 单插件，内部模块化组织
- **语言**：Python 3.12+

### SQLite（本地数据库）

- **职责**：用户配置、追番列表、别名映射、观看记录、访谈记录、任务状态
- **位置**：插件 data 目录下

### Markdown 文件存储

- **职责**：观感记录、对话记录
- **位置**：插件 data 目录下 `{data_path}/anime_notes/`（用户可通过配置自定义路径）
- **格式**：YAML frontmatter + Markdown 正文，兼容 Obsidian

### Bangumi API（外部服务）

- **职责**：番剧搜索、收藏管理、观看进度同步
- **API 版本**：v0
- **认证**：Personal Access Token (Bearer)
- **地址**：https://api.bgm.tv

### LLM（可替换）

- **职责**：访谈问题生成、观点总结、追问
- **选项**：OpenAI / Claude / Gemini / DeepSeek 均可
- **调用方式**：通过 AstrBot 内置 LLM 调用，或直接 HTTP API
