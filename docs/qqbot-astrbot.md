# QQ 官方机器人 与 AstrBot 连接方案

## 架构关系

```
┌──────────────┐    QQ Bot API     ┌──────────┐
│  QQ 官方机器人  │ ───────────────▶ │  AstrBot  │
│  (QQ开放平台)   │  Webhook/WebSocket │ (Bot框架) │
└──────────────┘                   └──────────┘
      │                                  │
      │  收发消息                         │  插件系统
      │  事件推送                         │  LLM 调用
      │                                  │  定时任务
      ▼                                  ▼
   QQ 服务器                           你的追番插件
```

**QQ 官方机器人**通过 QQ 开放平台直接与 QQ 服务器通信，无需额外中间件。

**AstrBot** 是"大脑"——负责理解消息、调用插件、调用 LLM。

两者通过 **QQ Bot API**（Webhook 或 WebSocket）通信。

## 前置准备

### 1. 注册 QQ 开放平台应用

1. 访问 [QQ 开放平台](https://q.qq.com/) 注册开发者账号
2. 创建机器人应用，获取：
   - **AppID**（机器人 ID）
   - **AppSecret**（机器人密钥）
   - **Token**（回调验证 Token）

### 2. 部署 AstrBot

```yaml
version: '3.8'

services:
  astrbot:
    image: soulter/astrbot:latest
    container_name: astrbot
    ports:
      - "6185:6185"               # AstrBot WebUI
    volumes:
      - ./astrbot/data:/app/data
    restart: unless-stopped
```

```bash
# 创建目录并启动
mkdir bangumibot && cd bangumibot
# 创建 docker-compose.yml（内容见上）
docker compose up -d
```

### 3. 配置 QQ 官方机器人适配器

1. 浏览器访问 `http://localhost:6185`（AstrBot WebUI）
2. **适配器管理** → **添加适配器**：
   - 类型: `QQ 官方机器人`
   - 填入 AppID、AppSecret、Token
3. **LLM 配置**（以 DeepSeek 为例）：
   - Provider: DeepSeek
   - API Key: 你的 DeepSeek API Key
   - Model: `deepseek-chat`
4. 确认适配器状态显示"已连接"

### 4. 验证连接

在 QQ 上对机器人发消息，AstrBot 日志中应出现消息事件。如果未回复，检查：

1. QQ 开放平台中机器人是否已上线
2. AstrBot WebUI 中适配器状态是否为"已连接"
3. AstrBot 是否已配置 LLM

## 与 NapCat 方案的对比

| 维度 | QQ 官方机器人 | NapCat |
|------|-------------|--------|
| 部署复杂度 | 低，无需额外容器 | 需额外部署 NapCat 容器 |
| 稳定性 | 官方 API，稳定 | 依赖第三方适配，可能触发风控 |
| 功能限制 | 受官方 API 限制（如群聊权限） | 功能更完整，接近普通 QQ 客户端 |
| 维护成本 | 低 | 需关注 NapCat 更新和风控策略 |
| 适用场景 | 个人使用、小规模 | 需要完整 QQ 功能时 |

## 扩展方案：NapCat 接入（未来可选）

如果后续需要 QQ 官方机器人不支持的功能（如主动加群、更灵活的群消息），可切换到 NapCat 方案：

```
┌─────────┐      WebSocket       ┌──────────┐
│  NapCat  │ ──────────────────▶ │  AstrBot  │
│ (QQ适配) │   OneBot v11 协议    │ (Bot框架) │
└─────────┘                      └──────────┘
```

部署方式参考 [NapCat 官方文档](https://docs.napneko.com/)，通过 OneBot v11 适配器连接 AstrBot。核心步骤：

1. Docker 部署 NapCat：`mlikiowa/napcat-docker:latest`
2. 访问 NapCat WebUI (端口 6099)，扫码登录 QQ
3. 配置反向 WebSocket 连接到 AstrBot 的 6199 端口
4. AstrBot 中添加 `aiocqhttp` 适配器

> **风险提醒**：NapCat 方案存在触发腾讯风控的风险，不建议使用新注册的 QQ 号，需合理控制消息发送频率。
