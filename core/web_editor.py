"""Web 笔记编辑器 — 通过浏览器直接编辑 Markdown 原文。"""

import html as html_mod
import logging
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)

SEASON_NAMES = {"1": "冬季", "4": "春季", "7": "夏季", "10": "秋季"}

# 与查看端口保持一致的配色
CSS = """
:root {
  --bg: #fdf6f0;
  --card: #fffbf7;
  --border: #e8d5c4;
  --text: #3b2e24;
  --muted: #9b8574;
  --accent: #d4814b;
  --accent-dim: #c06a32;
  --link: #b85c2e;
  --blockquote-bg: #fef9f3;
  --tag-bg: #fef3e8;
  --tag-hover-bg: #fde4cf;
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

.container { max-width: 960px; margin: 0 auto; padding: 24px 20px 60px; }

header {
  text-align: center; padding: 48px 0 32px;
  border-bottom: 1px solid var(--border); margin-bottom: 40px;
}
header h1 { font-size: 28px; font-weight: 700; color: #5c3d2e; }
header h1 span { color: var(--accent); }

.breadcrumb { font-size: 13px; color: var(--muted); margin-bottom: 24px; }
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--link); }

/* flash */
.flash {
  padding: 12px 16px; border-radius: var(--radius); margin-bottom: 20px;
  font-size: 14px; text-align: center;
}
.flash-success { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
.flash-error   { background: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }

/* index */
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

/* editor */
.editor-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.editor-label { font-size: 15px; color: var(--text); font-weight: 600; }
.editor-textarea {
  width: 100%; min-height: 70vh; padding: 16px;
  border: 1px solid var(--border); border-radius: var(--radius);
  font-size: 14px; line-height: 1.6;
  font-family: "SF Mono", "Fira Code", "Cascadia Code", "JetBrains Mono",
               "Noto Sans Mono SC", Menlo, Consolas, monospace;
  background: var(--card); color: var(--text);
  resize: vertical; box-sizing: border-box;
}
.editor-textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(212,129,75,.15);
}
.editor-actions {
  margin-top: 16px; display: flex; gap: 12px; align-items: center;
}
.btn {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 8px 24px; font-size: 14px; border: 1px solid var(--border);
  border-radius: var(--radius); cursor: pointer; font-family: inherit;
  transition: background .15s, border-color .15s;
}
.btn-save { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-save:hover { background: var(--accent-dim); }
.btn-back { background: var(--card); color: var(--muted); }
.btn-back:hover { background: var(--tag-hover-bg); color: var(--text); }

footer {
  text-align: center; color: var(--muted); font-size: 12px;
  padding: 40px 0 20px; border-top: 1px solid var(--border); margin-top: 60px;
}
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BangumiBot · 笔记编辑</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<header>
  <h1><span>BangumiBot</span> 笔记编辑</h1>
</header>
{body}
<footer>BangumiBot — 编辑端口</footer>
</div>
</body>
</html>"""

EDIT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>编辑 · {title}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<div class="breadcrumb">
  <a href="/">笔记编辑</a> / {season_cn} / {title}
</div>
{flash}
<div class="editor-toolbar">
  <span class="editor-label">Markdown 原文</span>
</div>
<form method="post" action="/edit/{encoded_season}/{encoded_anime}">
  <textarea name="content" class="editor-textarea" spellcheck="false">{content_escaped}</textarea>
  <div class="editor-actions">
    <button type="submit" class="btn btn-save"
            onclick="return confirm('确定保存？将覆盖文件全部内容。')">保存</button>
    <a href="/" class="btn btn-back">取消</a>
  </div>
</form>
<footer>BangumiBot — 编辑端口</footer>
</div>
</body>
</html>"""


def _validate_params(season: str, anime: str) -> None:
    """防止路径遍历攻击。"""
    if ".." in season or ".." in anime or "/" in season or "/" in anime:
        raise web.HTTPNotFound()


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
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/edit/{season}/{anime}", self._handle_edit)
        self._app.router.add_post("/edit/{season}/{anime}", self._handle_save)

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

    async def _handle_index(self, request: web.Request) -> web.Response:
        seasons = self._storage.list_seasons()
        if not seasons:
            html = INDEX_HTML.format(
                css=CSS,
                body='<div class="empty">暂无观感记录。</div>',
            )
            return web.Response(text=html, content_type="text/html", charset="utf-8")

        cards = []
        for season in sorted(seasons, reverse=True):
            animes = self._storage.list_animes(season)
            year, month = season.split(".")
            season_cn = f"{year}年{SEASON_NAMES.get(month, month)}季"
            encoded_season = quote(season)
            links = "\n".join(
                f'<li><a href="/edit/{encoded_season}/{quote(anime)}">{html_mod.escape(anime)}</a></li>'
                for anime in sorted(animes)
            )
            cards.append(
                f'<div class="season-card">'
                f'<h2>{season_cn} <span style="color:var(--muted);font-size:13px;font-weight:400">({len(animes)}部)</span></h2>'
                f'<ul class="anime-list">{links}</ul>'
                f'</div>'
            )

        html = INDEX_HTML.format(css=CSS, body="\n".join(cards))
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _handle_edit(self, request: web.Request) -> web.Response:
        season = request.match_info["season"]
        anime = request.match_info["anime"]
        _validate_params(season, anime)

        content = self._storage.load_anime(anime, season)
        if content is None:
            raise web.HTTPNotFound()

        # flash message from previous save
        flash = ""
        if request.query.get("saved") == "1":
            flash = '<div class="flash flash-success">已保存</div>'

        year, month = season.split(".")
        season_cn = f"{year}年{SEASON_NAMES.get(month, month)}季"

        html = EDIT_HTML.format(
            css=CSS,
            title=html_mod.escape(anime),
            season_cn=season_cn,
            flash=flash,
            encoded_season=quote(season),
            encoded_anime=quote(anime),
            content_escaped=html_mod.escape(content),
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _handle_save(self, request: web.Request) -> web.Response:
        season = request.match_info["season"]
        anime = request.match_info["anime"]
        _validate_params(season, anime)

        data = await request.post()
        content = data.get("content", "")

        if not content.strip():
            raise web.HTTPBadRequest(text="内容不能为空")

        self._storage.save_anime(anime, season, content)

        location = f"/edit/{quote(season)}/{quote(anime)}?saved=1"
        raise web.HTTPFound(location=location)
