"""Web 笔记编辑器 — 文件管理侧边栏 + 全文本编辑。"""

import html as html_mod
import logging
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)

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
  --danger-dim: #c62828;
  --hover-bg: #fef3e8;
  --active-bg: #fde4cf;
  --radius: 6px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  height: 100vh; overflow: hidden; display: flex;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------- layout ---------- */
.layout { display: flex; height: 100vh; }

.sidebar {
  min-width: 270px; max-width: 270px;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  padding: 16px 16px 12px; font-size: 16px; font-weight: 700;
  color: #5c3d2e; border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.sidebar-tools {
  padding: 10px 12px; display: flex; gap: 6px; flex-shrink: 0;
}
.sidebar-tools summary {
  padding: 4px 12px; font-size: 12px; border: 1px solid var(--border);
  border-radius: var(--radius); cursor: pointer; background: var(--card);
  color: var(--text); user-select: none;
}
.sidebar-tools summary:hover { background: var(--hover-bg); }
.tool-form {
  padding: 8px 0; display: flex; flex-direction: column; gap: 6px;
}
.tool-form select, .tool-form input {
  padding: 4px 8px; border: 1px solid var(--border);
  border-radius: 4px; font-size: 13px; font-family: inherit;
  background: var(--card);
}
.tool-form .btn-row { display: flex; gap: 6px; }
.tool-form .btn-row button {
  padding: 3px 12px; font-size: 12px; border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; font-family: inherit;
}
.tool-form .btn-row .btn-ok { background: var(--accent); color: #fff; border-color: var(--accent); }
.tool-form .btn-row .btn-ok:hover { background: var(--accent-dim); }
.tool-form .btn-row .btn-cancel { background: var(--card); color: var(--muted); }

.file-tree {
  flex: 1; overflow-y: auto; padding: 4px 0 20px; font-size: 13px;
}
.file-tree details { margin: 0; }
.file-tree summary {
  padding: 4px 16px 4px 0; cursor: pointer; user-select: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: #5c3d2e; font-weight: 500;
}
.file-tree summary:hover { background: var(--hover-bg); }
.file-tree summary::-webkit-details-marker { margin-left: 12px; }

.file-tree .tree-item {
  display: flex; align-items: center; padding: 3px 16px 3px 0;
  white-space: nowrap;
}
.file-tree .tree-item:hover { background: var(--hover-bg); }
.file-tree .tree-item.active { background: var(--active-bg); font-weight: 600; }

.file-tree .tree-link {
  flex: 1; overflow: hidden; text-overflow: ellipsis;
  color: var(--text); padding: 3px 0;
}
.file-tree .tree-link:hover { text-decoration: none; color: var(--link); }

.file-tree .del-btn {
  flex-shrink: 0; margin-left: 4px; padding: 1px 6px;
  font-size: 13px; border: none; background: transparent;
  color: var(--muted); cursor: pointer; border-radius: 3px;
  visibility: hidden;
}
.file-tree .tree-item:hover .del-btn { visibility: visible; }
.file-tree .del-btn:hover { background: var(--danger); color: #fff; }

.file-tree .tree-children { margin-left: 0; }
.file-tree details[open] > .tree-children { margin-left: 16px; }

.file-tree .empty-hint {
  padding: 16px; color: var(--muted); font-size: 12px; text-align: center;
}

/* ---------- main ---------- */
.main {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
}

.main-header {
  padding: 12px 20px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 12px; flex-shrink: 0;
  font-size: 13px; color: var(--muted);
}
.main-header .file-path { color: var(--text); font-weight: 500; }

.main-body {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
  padding: 16px 20px;
}

/* flash */
.flash {
  padding: 10px 14px; border-radius: var(--radius); margin-bottom: 12px;
  font-size: 13px; flex-shrink: 0;
}
.flash-success { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
.flash-error   { background: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }

/* editor */
.editor-form { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.editor-textarea {
  flex: 1; width: 100%; padding: 14px; border: 1px solid var(--border);
  border-radius: var(--radius); font-size: 14px; line-height: 1.7;
  font-family: "SF Mono", "Fira Code", "Cascadia Code", "JetBrains Mono",
               "Noto Sans Mono SC", Menlo, Consolas, monospace;
  background: var(--card); color: var(--text); resize: none;
}
.editor-textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(212,129,75,.15);
}

.editor-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 12px; flex-shrink: 0;
}
.editor-toolbar .hint { font-size: 12px; color: var(--muted); }
.btn {
  padding: 7px 20px; font-size: 13px; border: 1px solid var(--border);
  border-radius: var(--radius); cursor: pointer; font-family: inherit;
  transition: background .15s;
}
.btn-save { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-save:hover { background: var(--accent-dim); }
.btn-back { background: var(--card); color: var(--muted); }
.btn-back:hover { background: var(--hover-bg); color: var(--text); }

/* empty state */
.empty-state {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 15px; text-align: center;
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
<body class="layout">
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

<main class="main">
  {main_content}
</main>

<script>
// Ctrl+S / Cmd+S to save
document.addEventListener('keydown', function(e) {{
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
    e.preventDefault();
    var form = document.getElementById('editor-form');
    if (form) form.submit();
  }}
}});
// Auto-dismiss flash
setTimeout(function() {{
  var flash = document.querySelector('.flash');
  if (flash) {{ flash.style.opacity = '0'; flash.style.transition = 'opacity 0.5s'; }}
}}, 4000);
</script>
</body>
</html>"""


def _validate_path(sub_path: str) -> None:
    """防止路径遍历攻击（Web 层校验）。"""
    if ".." in sub_path or sub_path.startswith("/") or "\\" in sub_path:
        raise web.HTTPBadRequest(text="无效的路径")


def _collect_dirs(storage: MarkdownStorage, sub_path: str = "") -> list[str]:
    """递归收集所有目录路径，用于父目录下拉框。"""
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
    """递归渲染文件树 HTML。"""
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
        html += f'<details open>'
        html += f'<summary>{html_mod.escape(d)}/</summary>'
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
            f'<a href="/?path={encoded}" class="tree-link">{escaped_f}</a>'
            f'{delete_form}'
            f'</div>'
        )

    # 空文件夹：显示 × 删除按钮
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


def _render_main(path: str, flash_html: str,
                 content: str | None, error: str | None) -> str:
    """渲染主区域 HTML。"""
    if error:
        return (
            f'<div class="main-header">'
            f'<span>错误</span>'
            f'</div>'
            f'<div class="main-body">'
            f'{flash_html}'
            f'<div class="empty-state">⚠️ {html_mod.escape(error)}</div>'
            f'</div>'
        )

    if path and content is not None:
        encoded_path = html_mod.escape(path)
        quoted_path = quote(path)
        return (
            f'<div class="main-header">'
            f'<span>📝</span>'
            f'<span class="file-path">{encoded_path}</span>'
            f'</div>'
            f'<div class="main-body">'
            f'{flash_html}'
            f'<form id="editor-form" method="post" action="/api/save" class="editor-form">'
            f'<input type="hidden" name="path" value="{encoded_path}">'
            f'<textarea name="content" class="editor-textarea" spellcheck="false" '
            f'autofocus>{html_mod.escape(content)}</textarea>'
            f'<div class="editor-toolbar">'
            f'<span class="hint">Ctrl+S 保存</span>'
            f'<div>'
            f'<a href="/" class="btn btn-back">放弃</a>'
            f'<button type="submit" class="btn btn-save">保存</button>'
            f'</div>'
            f'</div>'
            f'</form>'
            f'</div>'
        )

    # 空状态
    return (
        f'<div class="main-header">'
        f'<span>📝 笔记编辑</span>'
        f'</div>'
        f'<div class="main-body">'
        f'{flash_html}'
        f'<div class="empty-state">'
        f'从左侧文件树选择文件开始编辑<br><br>'
        f'<span style="font-size:13px;color:var(--muted)">'
        f'或使用上方按钮新建文件 / 文件夹'
        f'</span>'
        f'</div>'
        f'</div>'
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
        """渲染主页（侧边栏 + 主区域）。"""
        active_path = request.query.get("path", "")
        flash_type = ""
        error = None
        content = None

        if request.query.get("saved") == "1":
            flash_type = "success"
            flash_msg = "已保存"
        elif request.query.get("created") == "1":
            flash_type = "success"
            flash_msg = "已创建"
        elif request.query.get("deleted") == "1":
            flash_type = "success"
            flash_msg = "已删除"
        elif (msg := request.query.get("error")):
            flash_type = "error"
            flash_msg = msg
        else:
            flash_msg = ""

        flash_html = ""
        if flash_msg:
            css_class = f"flash-{flash_type}" if flash_type else "flash-success"
            flash_html = f'<div class="flash {css_class}">{html_mod.escape(flash_msg)}</div>'

        if active_path:
            try:
                _validate_path(active_path)
            except web.HTTPBadRequest:
                error = "无效的文件路径"
            if not error:
                content = self._storage.load_file(active_path)
                if content is None:
                    error = f"文件不存在：{active_path}"

        # 父目录选项
        dirs = _collect_dirs(self._storage)
        parent_options = "\n".join(
            f'<option value="{html_mod.escape(d)}">{d or "根目录"}</option>'
            for d in dirs
        )

        # 文件树
        tree = _render_tree(self._storage, "", active_path)

        # 主区域
        main_content = _render_main(active_path, flash_html, content, error)

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
        if ok:
            location = f"/?path={quote(path)}&saved=1"
        else:
            location = f"/?path={quote(path)}&error=保存失败"
        raise web.HTTPFound(location=location)

    async def _handle_create_file(self, request: web.Request) -> web.Response:
        data = await request.post()
        parent_path = data.get("parent_path", "").strip()
        filename = data.get("filename", "").strip()

        try:
            _validate_path(parent_path)
        except web.HTTPBadRequest:
            location = "/?error=无效的父目录路径"
            raise web.HTTPFound(location=location)

        if not filename:
            location = "/?error=文件名不能为空"
            raise web.HTTPFound(location=location)

        ok, result = self._storage.create_file(parent_path, filename)
        if ok:
            location = f"/?path={quote(result)}&created=1"
        else:
            location = f"/?error={quote(result)}"
        raise web.HTTPFound(location=location)

    async def _handle_create_dir(self, request: web.Request) -> web.Response:
        data = await request.post()
        parent_path = data.get("parent_path", "").strip()
        dirname = data.get("dirname", "").strip()

        try:
            _validate_path(parent_path)
        except web.HTTPBadRequest:
            location = "/?error=无效的父目录路径"
            raise web.HTTPFound(location=location)

        if not dirname:
            location = "/?error=文件夹名不能为空"
            raise web.HTTPFound(location=location)

        ok, result = self._storage.create_directory(parent_path, dirname)
        if ok:
            location = f"/?created=1"
        else:
            location = f"/?error={quote(result)}"
        raise web.HTTPFound(location=location)

    async def _handle_delete(self, request: web.Request) -> web.Response:
        data = await request.post()
        path = data.get("path", "").strip()

        try:
            _validate_path(path)
        except web.HTTPBadRequest:
            location = "/?error=无效的路径"
            raise web.HTTPFound(location=location)

        ok, msg = self._storage.delete_path(path)
        if ok:
            location = f"/?deleted=1"
        else:
            location = f"/?error={quote(msg)}"
        raise web.HTTPFound(location=location)
