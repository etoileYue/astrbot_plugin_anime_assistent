# 远程查看 bangumi.db 数据库

## 数据库位置

容器内路径：`/app/data/plugin_data/bangumibot/bangumi.db`
宿主机路径：`./astrbot/data/plugin_data/bangumibot/bangumi.db`（相对于 docker-compose.yml 所在目录）

## 方案一：Docker 容器内 sqlite3 CLI（最简）

在容器内直接使用 `sqlite3` 命令行：

```bash
# 进入容器并打开数据库
docker exec -it astrbot sqlite3 /app/data/plugin_data/bangumibot/bangumi.db

# 常用 sqlite3 命令
.tables                          # 列出所有表
.schema subscriptions            # 查看表结构
.mode column                     # 列对齐输出
.headers on                      # 显示列名
SELECT * FROM subscriptions;     # 查看追番列表
SELECT * FROM watch_log ORDER BY watched_at DESC LIMIT 20;  # 最近观看记录
SELECT * FROM interviews;        # 访谈记录
.quit                            # 退出
```

如果容器内没有 `sqlite3`，先安装：

```bash
docker exec -it astrbot apt-get update && apt-get install -y sqlite3
```

### 一行查询（不进入交互模式）

```bash
# 查看追番列表
docker exec -it astrbot sqlite3 -header -column \
  /app/data/plugin_data/bangumibot/bangumi.db \
  "SELECT id, subject_name, status, watched_eps, total_eps FROM subscriptions;"

# 查看最近观看记录
docker exec -it astrbot sqlite3 -header -column \
  /app/data/plugin_data/bangumibot/bangumi.db \
  "SELECT * FROM watch_log ORDER BY watched_at DESC LIMIT 10;"
```

## 方案二：导出到本地查看

将数据库文件从服务器拷贝到本地，用图形化工具查看：

```bash
# 在本地执行（假设远程服务器 ssh 别名为 myserver）
scp myserver:~/bangumibot/astrbot/data/plugin_data/bangumibot/bangumi.db ./
```

### 本地工具推荐

| 工具 | 平台 | 说明 |
|------|------|------|
| [DB Browser for SQLite](https://sqlitebrowser.org/) | Win/Mac/Linux | 免费开源，图形界面 |
| VSCode + SQLite 插件 | 全平台 | 在编辑器中直接查看，推荐 `alexcvzz.vscode-sqlite` |
| JetBrains DataGrip | 全平台 | 功能最强，需付费 |
| `sqlite3` CLI | 全平台 | 命令行，无需安装额外工具 |

### VSCode 方式（推荐）

1. 安装插件 `SQLite`（作者 alexcvzz）
2. 将 `bangumi.db` 拷贝到本地后，在 VSCode 中右键 `bangumi.db` → "Open Database"
3. 左侧出现 SQLite Explorer，可浏览表和数据

## 方案三：Web 端查看（Docker 服务）

在远程服务器上运行轻量级 SQLite Web 浏览器，通过浏览器访问：

```bash
# 使用 sqlite-web（Python 工具）
docker run --rm -d \
  --name sqlite-web \
  -p 8080:8080 \
  -v $(pwd)/astrbot/data/plugin_data/bangumibot:/data \
  coleifer/sqlite-web /data/bangumi.db -H 0.0.0.0

# 浏览器访问 http://<服务器IP>:8080
```

用完记得关闭：`docker stop sqlite-web`

> **安全提醒**：`sqlite-web` 无认证机制，暴露在公网会有安全风险。建议配合 SSH 端口转发使用：
> ```bash
> # 在本地执行，将远程 8080 映射到本地 8080
> ssh -L 8080:localhost:8080 myserver
> # 然后浏览器访问 http://localhost:8080
> ```

## 方案四：SSH 隧道 + DB Browser

不拷贝文件，直接通过 SSH 隧道远程打开数据库：

1. 在本地建立 SSH 隧道挂载远程目录：
   ```bash
   # macOS
   sshfs myserver:~/bangumibot/astrbot/data/plugin_data/bangumibot ./remote-db
   
   # Linux
   sshfs myserver:~/bangumibot/astrbot/data/plugin_data/bangumibot ./remote-db
   ```

2. 用 DB Browser for SQLite 打开 `./remote-db/bangumi.db`

> **注意**：sshfs 对大文件性能一般，但 SQLite 查询通常只读取所需页面，日常使用足够。

## 常用查询参考

```sql
-- 追番列表（含状态中文）
SELECT 
    id,
    subject_name AS '番剧名',
    CASE status
        WHEN 1 THEN '想看' WHEN 2 THEN '看过'
        WHEN 3 THEN '在看' WHEN 4 THEN '搁置' WHEN 5 THEN '抛弃'
    END AS '状态',
    watched_eps || '/' || total_eps AS '进度'
FROM subscriptions;

-- 别名列表
SELECT s.subject_name, a.alias
FROM aliases a
JOIN subscriptions s ON a.subject_id = s.subject_id;

-- 最近7天观看记录
SELECT s.subject_name, w.episode, w.watched_at, w.source
FROM watch_log w
JOIN subscriptions s ON w.subject_id = s.subject_id
WHERE w.watched_at >= datetime('now', '-7 days')
ORDER BY w.watched_at DESC;

-- 未完成的访谈
SELECT s.subject_name, i.episode, i.question, i.answer, i.round
FROM interviews i
JOIN subscriptions s ON i.subject_id = s.subject_id
WHERE i.answer IS NULL;
```

## 推荐方案总结

| 场景 | 推荐方案 |
|------|---------|
| 快速看一眼数据 | 方案一（docker exec + sqlite3） |
| 经常需要查看、做数据分析 | 方案二（拷到本地 + VSCode/DB Browser） |
| 团队共享、需要 Web 界面 | 方案三（sqlite-web + SSH 隧道） |
| 不想拷贝文件又需要图形界面 | 方案四（sshfs） |
