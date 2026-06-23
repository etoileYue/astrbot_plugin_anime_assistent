"""Web 笔记编辑器 — 类 WebViewer 布局 + 可收起侧边栏。"""

import html as html_mod
import logging
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)

SEASON_NAMES = {"1": "冬季", "4": "春季", "7": "夏季", "10": "秋季"}

CSS = """
:root {
  --bg: #fdf6f0;
  --sidebar-bg: #f8f0e8;
  --card: #fffbf7;
  --border: #e8d5c4;
  --text: #3b2e24;
  --muted: #9b8574;
  --accent: #d4814b;
  --accent-dim: #c06a32;
  --link: #b85c2e;
  --danger: #e57373;
  --hover-bg: #fef3e8;
  --active-bg: #fde4cf;
  --tag-bg: #fef3e8;
  --tag-hover-bg: #fde4cf;
  --blockquote-bg: #fef9f3;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,.04);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.7;
  min-height: 100vh;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------- sidebar toggle ---------- */
.sidebar-toggle {
  position: fixed; top: 16px; left: 16px; z-index: 101;
  width: 40px; height: 40px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--card);
  cursor: pointer; font-size: 18px; color: var(--text);
  display: flex; align-items: center; justify-content: center;
  transition: left 0.25s ease, box-shadow 0.25s;
  box-shadow: var(--shadow);
}
.sidebar-toggle:hover { box-shadow: 0 2px 6px rgba(0,0,0,.08); }
body.sidebar-open .sidebar-toggle { left: 296px; }

/* ---------- sidebar overlay ---------- */
.sidebar-overlay {
  position: fixed; inset: 0; z-index: 99;
  background: rgba(0,0,0,.2); opacity: 0; pointer-events: none;
  transition: opacity 0.25s;
}
body.sidebar-open .sidebar-overlay { opacity: 1; pointer-events: auto; }

/* ---------- sidebar panel ---------- */
.sidebar {
  position: fixed; left: 0; top: 0; height: 100vh; width: 280px; z-index: 100;
  background: var(--sidebar-bg); border-right: 1px solid var(--border);
  box-shadow: 2px 0 8px rgba(0,0,0,.06);
  transform: translateX(-100%); transition: transform 0.25s ease;
  display: flex; flex-direction: column; overflow: hidden;
}
body.sidebar-open .sidebar { transform: translateX(0); }

.sidebar-header {
  padding: 18px 16px 14px; font-size: 15px; font-weight: 700;
  color: #5c3d2e; border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  letter-spacing: 0.02em;
}
.sidebar-tools {
  padding: 10px 12px; display: flex; gap: 6px; flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.sidebar-tools details { position: relative; }
.sidebar-tools summary {
  padding: 5px 12px; font-size: 12px; border: 1px solid var(--border);
  border-radius: 6px; cursor: pointer; background: var(--card);
  color: var(--text); user-select: none; list-style: none;
  transition: background 0.15s, border-color 0.15s;
}
.sidebar-tools summary::-webkit-details-marker { display: none; }
.sidebar-tools summary:hover { background: var(--active-bg); border-color: var(--accent-dim); }
.tool-form {
  padding: 8px 0; display: flex; flex-direction: column; gap: 6px;
}
.tool-form select, .tool-form input {
  padding: 5px 8px; border: 1px solid var(--border);
  border-radius: 5px; font-size: 12px; font-family: inherit;
  background: var(--card); transition: border-color 0.15s;
}
.tool-form select:focus, .tool-form input:focus {
  outline: none; border-color: var(--accent);
}
.tool-form .btn-row { display: flex; gap: 6px; }
.tool-form .btn-row button {
  padding: 4px 14px; font-size: 12px; border: 1px solid var(--border);
  border-radius: 5px; cursor: pointer; font-family: inherit;
  transition: background 0.15s;
}
.tool-form .btn-row .btn-ok { background: var(--accent); color: #fff; border-color: var(--accent); }
.tool-form .btn-row .btn-ok:hover { background: var(--accent-dim); }

/* ---------- file tree ---------- */
.file-tree {
  flex: 1; overflow-y: auto; padding: 8px 0 20px; font-size: 13px;
}
.file-tree details { margin: 0; }

/* hide browser default marker, use custom chevron */
.file-tree summary {
  list-style: none;
  padding: 6px 16px 6px 28px;
  cursor: pointer; user-select: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: #5c3d2e; font-weight: 500; font-size: 13px;
  position: relative;
  transition: background 0.15s, color 0.15s;
  border-radius: 0 6px 6px 0;
}
.file-tree summary::-webkit-details-marker { display: none; }
.file-tree summary::before {
  content: "";
  position: absolute; left: 10px; top: 50%; margin-top: -4px;
  width: 0; height: 0;
  border-left: 5px solid var(--muted);
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  transition: transform 0.2s ease, border-left-color 0.15s;
}
.file-tree details[open] > summary::before {
  transform: rotate(90deg);
}
.file-tree summary:hover {
  background: var(--hover-bg);
}
.file-tree summary:hover::before {
  border-left-color: var(--accent);
}

/* tree children with connecting line */
.file-tree .tree-children {
  margin-left: 12px;
  border-left: 1px solid var(--border);
  padding-left: 0;
}

/* file / empty-folder items */
.file-tree .tree-item {
  display: flex; align-items: center;
  padding: 5px 16px 5px 20px;
  white-space: nowrap;
  position: relative;
  transition: background 0.15s;
  border-radius: 0 6px 6px 0;
}
/* horizontal connector line */
.file-tree .tree-item::before {
  content: "";
  position: absolute; left: 0; top: 50%;
  width: 10px; height: 0;
  border-top: 1px solid var(--border);
}
.file-tree .tree-item:hover { background: var(--hover-bg); }
.file-tree .tree-item.active {
  background: var(--active-bg);
  font-weight: 600;
}
.file-tree .tree-item.active::after {
  content: "";
  position: absolute; left: 0; top: 4px; bottom: 4px;
  width: 3px; background: var(--accent); border-radius: 0 2px 2px 0;
}

.file-tree .tree-link {
  flex: 1; overflow: hidden; text-overflow: ellipsis;
  color: var(--text); padding: 2px 0; font-size: 13px;
  transition: color 0.15s;
}
.file-tree .tree-link:hover { text-decoration: none; color: var(--link); }

/* icons before file/folder names */
.file-tree .tree-icon {
  flex-shrink: 0; width: 18px; font-size: 12px; text-align: center;
  margin-right: 4px; opacity: 0.6;
}

/* delete button */
.file-tree .del-btn {
  flex-shrink: 0; margin-left: 4px;
  width: 20px; height: 20px; padding: 0;
  font-size: 14px; line-height: 1;
  border: none; background: transparent;
  color: var(--muted); cursor: pointer; border-radius: 4px;
  visibility: hidden;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s, color 0.15s, visibility 0.1s;
}
.file-tree .tree-item:hover .del-btn { visibility: visible; }
.file-tree .del-btn:hover { background: var(--danger); color: #fff; }

.file-tree .empty-hint {
  padding: 20px 16px; color: var(--muted); font-size: 12px;
  text-align: center; font-style: italic;
}

/* ---------- main container (matches WebViewer) ---------- */
.container { max-width: 860px; margin: 0 auto; padding: 24px 20px 60px; }

header {
  text-align: center; padding: 48px 0 32px;
  border-bottom: 1px solid var(--border); margin-bottom: 40px;
}
header h1 { font-size: 28px; font-weight: 700; color: #5c3d2e; }
header h1 span { color: var(--accent); }

.breadcrumb { font-size: 13px; color: var(--muted); margin-bottom: 24px; }
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--link); }

/* season cards (matches WebViewer) */
.season-grid { display: grid; gap: 20px; }
.season-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px 24px;
  box-shadow: var(--shadow);
}
.season-card h2 {
  font-size: 18px; margin-bottom: 14px; color: #5c3d2e;
}
.season-card .anime-list { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }
.season-card .anime-list li a {
  display: inline-block; padding: 6px 16px;
  background: var(--tag-bg); border-radius: 20px;
  font-size: 14px; color: #5c3d2e;
  border: 1px solid var(--border); transition: background .2s, border-color .2s;
}
.season-card .anime-list li a:hover {
  background: var(--tag-hover-bg); border-color: var(--accent-dim); text-decoration: none;
}

.empty {
  text-align: center; color: var(--muted); padding: 60px 0;
  font-size: 15px;
}

/* flash */
.flash {
  padding: 10px 14px; border-radius: var(--radius); margin-bottom: 12px;
  font-size: 13px; text-align: center;
}
.flash-success { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
.flash-error   { background: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }

/* editor */
.editor-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.editor-label { font-size: 15px; color: var(--text); font-weight: 600; }
.editor-textarea {
  width: 100%; min-height: 55vh; padding: 14px;
  border: 1px solid var(--border); border-radius: var(--radius);
  font-size: 14px; line-height: 1.7;
  font-family: "SF Mono", "Fira Code", "Cascadia Code", "JetBrains Mono",
               "Noto Sans Mono SC", Menlo, Consolas, monospace;
  background: var(--card); color: var(--text); resize: vertical;
}
.editor-textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(212,129,75,.15);
}
.editor-actions {
  margin-top: 14px; display: flex; gap: 12px; align-items: center;
}
.btn {
  padding: 7px 20px; font-size: 13px; border: 1px solid var(--border);
  border-radius: var(--radius); cursor: pointer; font-family: inherit;
  transition: background .15s;
}
.btn-save { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-save:hover { background: var(--accent-dim); }
.btn-back { background: var(--card); color: var(--muted); }
.btn-back:hover { background: var(--hover-bg); color: var(--text); }

footer {
  text-align: center; color: var(--muted); font-size: 12px;
  padding: 40px 0 20px; border-top: 1px solid var(--border); margin-top: 60px;
}
"""

PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BangumiBot · 笔记编辑</title>
<style>{css}</style>
</head>
<body>

<!-- 侧边栏切换按钮 -->
<button class="sidebar-toggle" onclick="toggleSidebar()" title="文件导航">☰</button>

<!-- 遮罩（点击关闭侧边栏） -->
<div class="sidebar-overlay" onclick="toggleSidebar()"></div>

<!-- 侧边栏：文件导航 -->
<aside class="sidebar">
  <div class="sidebar-header">📒 笔记文件</div>
  <div class="sidebar-tools">
    <details>
      <summary>📄 新建文件</summary>
      <form method="post" action="/api/create-file" class="tool-form">
        <select name="parent_path">
          <option value="">根目录</option>
          {parent_options}
        </select>
        <input name="filename" placeholder="文件名（自动加 .md）" required>
        <div class="btn-row">
          <button type="submit" class="btn-ok">创建</button>
        </div>
      </form>
    </details>
    <details>
      <summary>📁 新建文件夹</summary>
      <form method="post" action="/api/create-dir" class="tool-form">
        <select name="parent_path">
          <option value="">根目录</option>
          {parent_options}
        </select>
        <input name="dirname" placeholder="文件夹名" required>
        <div class="btn-row">
          <button type="submit" class="btn-ok">创建</button>
        </div>
      </form>
    </details>
  </div>
  <nav class="file-tree">
    {tree}
  </nav>
</aside>

<!-- 主内容区域（居中容器，与 WebViewer 一致） -->
<div class="container">
  {main_content}
</div>

<script>
function toggleSidebar() {{
  document.body.classList.toggle('sidebar-open');
}}

// 点击遮罩关闭
document.querySelector('.sidebar-overlay').addEventListener('click', function() {{
  document.body.classList.remove('sidebar-open');
}});

// Esc 关闭侧边栏
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') document.body.classList.remove('sidebar-open');
  // Ctrl+S 保存
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
    e.preventDefault();
    var form = document.getElementById('editor-form');
    if (form) form.submit();
  }}
}});

// Flash 自动消失
setTimeout(function() {{
  var flash = document.querySelector('.flash');
  if (flash) {{ flash.style.opacity = '0'; flash.style.transition = 'opacity 0.5s'; }}
}}, 4000);
</script>
</body>
</html>"""


def _validate_path(sub_path: str) -> None:
    if ".." in sub_path or sub_path.startswith("/") or "\\" in sub_path:
        raise web.HTTPBadRequest(text="无效的路径")


def _collect_dirs(storage: MarkdownStorage) -> list[str]:
    dirs = [""]
    try:
        for d in sorted(storage._base_dir.rglob("*")):
            if d.is_dir():
                try:
                    rel = str(d.relative_to(storage._base_dir))
                    dirs.append(rel)
                except ValueError:
                    pass
    except OSError:
        pass
    return dirs


def _render_tree(storage: MarkdownStorage, sub_path: str = "",
                 active_path: str = "", depth: int = 0) -> str:
    result = storage.list_directory(sub_path)
    dirs = result["dirs"]
    files = result["files"]

    if not dirs and not files:
        if depth == 0:
            return '<div class="empty-hint">暂无文件</div>'
        return ""

    html = ""
    for d in dirs:
        child_path = f"{sub_path}/{d}" if sub_path else d
        html += '<details open>'
        html += f'<summary><span class="tree-icon">📁</span>{html_mod.escape(d)}</summary>'
        html += '<div class="tree-children">'
        html += _render_tree(storage, child_path, active_path, depth + 1)
        html += '</div></details>'

    for f in files:
        file_path = f"{sub_path}/{f}" if sub_path else f
        active_class = ' active' if file_path == active_path else ''
        encoded = quote(file_path)
        escaped_f = html_mod.escape(f)
        escaped_fp = html_mod.escape(file_path)

        delete_form = (
            "<form method=\"post\" action=\"/api/delete\" style=\"margin:0;display:inline-flex\" "
            + f"onsubmit=\"return confirm('确定删除 {escaped_f}？')\">"
            + f"<input type=\"hidden\" name=\"path\" value=\"{escaped_fp}\">"
            + "<button type=\"submit\" class=\"del-btn\" title=\"删除\">×</button>"
            + "</form>"
        )

        html += (
            f'<div class="tree-item{active_class}">'
            f'<span class="tree-icon">📄</span>'
            f'<a href="/?path={encoded}" class="tree-link">{escaped_f}</a>'
            f'{delete_form}'
            f'</div>'
        )

    if depth > 0 and not dirs and not files:
        escaped_sub = html_mod.escape(sub_path)
        delete_form = (
            "<form method=\"post\" action=\"/api/delete\" style=\"margin:0;display:inline-flex\" "
            + "onsubmit=\"return confirm('确定删除空文件夹？')\">"
            + f"<input type=\"hidden\" name=\"path\" value=\"{escaped_sub}\">"
            + "<button type=\"submit\" class=\"del-btn\" title=\"删除空文件夹\" "
            + "style=\"visibility:visible;font-size:11px\">×</button>"
            + "</form>"
        )
        html += (
            '<div class="tree-item">'
            '<span class="tree-link" style="color:var(--muted);font-style:italic">空文件夹</span>'
            f'{delete_form}'
            '</div>'
        )

    return html


def _render_browse(storage: MarkdownStorage) -> str:
    """渲染季度卡片列表（类 WebViewer 风格）。"""
    seasons = storage.list_seasons()
    if not seasons:
        return (
            '<header>'
            '<h1><span>BangumiBot</span> 笔记编辑</h1>'
            '</header>'
            '<div class="empty">暂无观感记录。<br>'
            '点击左上角 ☰ 打开侧边栏新建文件。</div>'
            '<footer>BangumiBot — 编辑端口</footer>'
        )

    cards = []
    for season in sorted(seasons, reverse=True):
        animes = storage.list_animes(season)
        if not animes:
            continue
        # 支持 year.month 格式的季节目录，也支持普通目录名
        try:
            year, month = season.split(".")
            season_cn = f"{year}年{SEASON_NAMES.get(month, month)}季"
        except (ValueError, KeyError):
            season_cn = season

        links = "\n".join(
            f'<li><a href="/?path={quote(f"{season}/{anime}.md")}">{html_mod.escape(anime)}</a></li>'
            for anime in sorted(animes)
        )
        cards.append(
            f'<div class="season-card">'
            f'<h2>{season_cn} '
            f'<span style="color:var(--muted);font-size:13px;font-weight:400">'
            f'({len(animes)}部)</span></h2>'
            f'<ul class="anime-list">{links}</ul>'
            f'</div>'
        )

    return (
        '<header>'
        '<h1><span>BangumiBot</span> 笔记编辑</h1>'
        '</header>'
        f'<div class="season-grid">{"".join(cards)}</div>'
        '<footer>BangumiBot — 编辑端口</footer>'
    )


def _render_editor(path: str, content: str, flash_html: str) -> str:
    """渲染编辑器视图。"""
    encoded_path = html_mod.escape(path)

    # Parse season for breadcrumb
    parts = path.split("/")
    season_cn = ""
    if len(parts) >= 2:
        try:
            year, month = parts[0].split(".")
            season_cn = f"{year}年{SEASON_NAMES.get(month, month)}季 / "
        except (ValueError, KeyError):
            season_cn = f"{parts[0]} / "

    return (
        '<div class="breadcrumb">'
        '<a href="/">笔记编辑</a>'
        f' / {season_cn}{html_mod.escape(parts[-1])}'
        '</div>'
        f'{flash_html}'
        f'<div class="editor-toolbar">'
        f'<span class="editor-label">Markdown 原文</span>'
        f'</div>'
        f'<form id="editor-form" method="post" action="/api/save">'
        f'<input type="hidden" name="path" value="{encoded_path}">'
        f'<textarea name="content" class="editor-textarea" spellcheck="false" '
        f'autofocus>{html_mod.escape(content)}</textarea>'
        f'<div class="editor-actions">'
        f'<span style="font-size:12px;color:var(--muted);flex:1">Ctrl+S 保存</span>'
        f'<a href="/" class="btn btn-back">放弃</a>'
        "<button type=\"submit\" class=\"btn btn-save\" "
        + "onclick=\"return confirm('确定保存？将覆盖文件全部内容。')\">保存</button>"
        f'</div>'
        f'</form>'
        '<footer>BangumiBot — 编辑端口</footer>'
    )


def _render_error(error: str, flash_html: str) -> str:
    return (
        '<header>'
        '<h1><span>BangumiBot</span> 笔记编辑</h1>'
        '</header>'
        f'{flash_html}'
        f'<div class="empty">⚠️ {html_mod.escape(error)}</div>'
        '<footer>BangumiBot — 编辑端口</footer>'
    )


class WebEditor:
    def __init__(self, notes_dir: str, host: str = "0.0.0.0", port: int = 58081):
        self._notes_dir = Path(notes_dir)
        self._host = host
        self._port = port
        self._storage = MarkdownStorage(notes_dir)
        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._setup_routes()

    def _setup_routes(self):
        self._app.router.add_get("/", self._handle_page)
        self._app.router.add_post("/api/save", self._handle_save)
        self._app.router.add_post("/api/create-file", self._handle_create_file)
        self._app.router.add_post("/api/create-dir", self._handle_create_dir)
        self._app.router.add_post("/api/delete", self._handle_delete)

    async def start(self):
        if self._port <= 0:
            logger.info("Web editor disabled (port=0)")
            return
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(f"Web editor started at http://{self._host}:{self._port}")

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            logger.info("Web editor stopped")

    async def _handle_page(self, request: web.Request) -> web.Response:
        active_path = request.query.get("path", "")
        flash_type = ""
        flash_msg = ""
        error = None
        content = None

        if request.query.get("saved") == "1":
            flash_type, flash_msg = "success", "已保存"
        elif request.query.get("created") == "1":
            flash_type, flash_msg = "success", "已创建"
        elif request.query.get("deleted") == "1":
            flash_type, flash_msg = "success", "已删除"
        elif (msg := request.query.get("error")):
            flash_type, flash_msg = "error", msg

        flash_html = ""
        if flash_msg:
            css_class = f"flash-{flash_type}" if flash_type else "flash-success"
            flash_html = (
                f'<div class="flash {css_class}">'
                f'{html_mod.escape(flash_msg)}</div>'
            )

        if active_path:
            try:
                _validate_path(active_path)
            except web.HTTPBadRequest:
                error = "无效的文件路径"
            if not error:
                content = self._storage.load_file(active_path)
                if content is None:
                    error = f"文件不存在：{active_path}"

        # 父目录选项（供侧边栏新建表单使用）
        dirs = _collect_dirs(self._storage)
        parent_options = "\n".join(
            f'<option value="{html_mod.escape(d)}">{d or "根目录"}</option>'
            for d in dirs
        )

        # 文件树
        tree = _render_tree(self._storage, "", active_path)

        # 主区域：浏览模式 / 编辑模式 / 错误
        if error:
            main_content = _render_error(error, flash_html)
        elif active_path and content is not None:
            main_content = _render_editor(active_path, content, flash_html)
        else:
            main_content = _render_browse(self._storage)

        html = PAGE_HTML.format(
            css=CSS,
            parent_options=parent_options,
            tree=tree,
            main_content=main_content,
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _handle_save(self, request: web.Request) -> web.Response:
        data = await request.post()
        path = data.get("path", "").strip()
        content = data.get("content", "")

        try:
            _validate_path(path)
        except web.HTTPBadRequest:
            return web.HTTPBadRequest(text="无效的路径")

        if not path:
            return web.HTTPBadRequest(text="缺少 path 参数")

        ok = self._storage.save_file(path, content)
        location = f"/?path={quote(path)}&saved=1" if ok else f"/?path={quote(path)}&error=保存失败"
        raise web.HTTPFound(location=location)

    async def _handle_create_file(self, request: web.Request) -> web.Response:
        data = await request.post()
        parent_path = data.get("parent_path", "").strip()
        filename = data.get("filename", "").strip()

        try:
            _validate_path(parent_path)
        except web.HTTPBadRequest:
            raise web.HTTPFound(location="/?error=无效的父目录路径")

        if not filename:
            raise web.HTTPFound(location="/?error=文件名不能为空")

        ok, result = self._storage.create_file(parent_path, filename)
        location = f"/?path={quote(result)}&created=1" if ok else f"/?error={quote(result)}"
        raise web.HTTPFound(location=location)

    async def _handle_create_dir(self, request: web.Request) -> web.Response:
        data = await request.post()
        parent_path = data.get("parent_path", "").strip()
        dirname = data.get("dirname", "").strip()

        try:
            _validate_path(parent_path)
        except web.HTTPBadRequest:
            raise web.HTTPFound(location="/?error=无效的父目录路径")

        if not dirname:
            raise web.HTTPFound(location="/?error=文件夹名不能为空")

        ok, result = self._storage.create_directory(parent_path, dirname)
        location = "/?created=1" if ok else f"/?error={quote(result)}"
        raise web.HTTPFound(location=location)

    async def _handle_delete(self, request: web.Request) -> web.Response:
        data = await request.post()
        path = data.get("path", "").strip()

        try:
            _validate_path(path)
        except web.HTTPBadRequest:
            raise web.HTTPFound(location="/?error=无效的路径")

        ok, msg = self._storage.delete_path(path)
        location = "/?deleted=1" if ok else f"/?error={quote(msg)}"
        raise web.HTTPFound(location=location)
