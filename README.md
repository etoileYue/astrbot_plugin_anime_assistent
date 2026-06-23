# BangumiBot

基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 框架的追番管理插件。通过 QQ 机器人管理 Bangumi 追番列表、同步观看进度、LLM 驱动的观感访谈、自动生成 Obsidian 兼容的 Markdown 观感记录。

## 功能

- **番剧搜索** — `/search 芙莉莲` 搜索 Bangumi 条目
- **追番管理** — `/sub add|list|remove` 管理追番列表
- **进度同步** — 发送"芙莉莲15看完"自动同步观看进度到 Bangumi
- **更新提醒** — 定时检查番剧更新，自动推送 QQ 通知
- **观感访谈** — 同步进度后 LLM 自动发起多轮访谈对话
- **Markdown 记录** — 访谈内容自动保存为 Obsidian 兼容的 Markdown 文件
- **Web 笔记查看** — 浏览器访问只读笔记页面（端口 58080）
- **Web 笔记编辑** — 独立的文件管理器 + Markdown 编辑器（端口 58081）

## 安装

1. 将 `astrbot_plugin_bangumi/` 放入 AstrBot 的 `addons/` 目录
2. 在 AstrBot WebUI 中启用插件
3. 配置 Bangumi Access Token（从 https://next.bgm.tv/demo/access-token 获取）

## 命令

| 命令 | 说明 |
|------|------|
| `/bangumi` | 查看所有可用命令 |
| `/search <关键词>` | 搜索 Bangumi 番剧 |
| `/sub add <id>` | 添加追番 |
| `/sub list` | 查看追番列表 |
| `/sub remove <id>` | 移除追番 |
| `/sub sync` | 从 Bangumi 同步「在看」列表 |
| `/sync` | 手动触发更新检查 |
| `/note <标识> <集数>` | 手动触发观感访谈 |
| `/notes list` | 查看观感记录 |

## Web 界面

插件启动后提供两个 Web 端口：

| 端口 | 用途 | 说明 |
|------|------|------|
| `58080` | **笔记查看器** | 只读浏览，可分享给他人 |
| `58081` | **笔记编辑器** | 文件管理 + Markdown 全文编辑 |

查看器展示渲染后的 HTML 页面；编辑器提供侧边栏文件树，支持新建/删除/编辑 Markdown 文件，Ctrl+S 保存。

端口号可在插件配置中修改（`web_viewer_port` / `web_editor_port`），设为 0 可禁用。

## 消息模式

发送 `番剧名 + 集数 + 看完/看到/追到` 即可自动同步进度，例如：

- `芙莉莲15看完`
- `葬送的芙莉莲看到第10集`

## 本地开发

无需部署到 AstrBot 即可在本地预览 Web 界面：

```bash
# 安装 Web 依赖
pip install aiohttp pyyaml markdown

# 启动开发服务器（自动创建示例数据）
python tools/dev_server.py

# 自动重载模式（修改代码后自动重启）
pip install watchfiles
python tools/dev_server.py --reload
```

启动后访问：
- `http://localhost:58080` — 查看器预览
- `http://localhost:58081` — 编辑器预览

## 文档

- `docs/architecture.md` — 系统架构
- `docs/development-plan.md` — 开发阶段
- `docs/modules.md` — 模块划分
- `docs/database.md` — 数据库设计
- `docs/bangumi-api.md` — Bangumi API 封装
- `docs/data-flow.md` — 数据流设计
- `docs/markdown-storage.md` — Markdown 存储
- `docs/qqbot-astrbot.md` — QQ 机器人配置
- `docs/adr/` — 架构决策记录

## 依赖

- Python 3.12+
- httpx, aiosqlite, aiohttp
- markdown, PyYAML
- AstrBot >= 4.16
