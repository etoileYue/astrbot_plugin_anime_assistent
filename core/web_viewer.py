"""Web 笔记查看器 — 通过浏览器浏览观感记录。"""

import logging
from pathlib import Path
import yaml
import markdown
from aiohttp import web

from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)

SEASON_NAMES = {"1": "冬季", "4": "春季", "7": "夏季", "10": "秋季"}

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
  --blockquote-border: #e8a87c;
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

.container { max-width: 860px; margin: 0 auto; padding: 24px 20px 60px; }

header {
  text-align: center; padding: 48px 0 32px;
  border-bottom: 1px solid var(--border); margin-bottom: 40px;
}
header h1 { font-size: 28px; font-weight: 700; color: #5c3d2e; }
header h1 span { color: var(--accent); }
header p { color: var(--muted); margin-top: 6px; font-size: 14px; }

.breadcrumb { font-size: 13px; color: var(--muted); margin-bottom: 24px; }
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--link); }

.season-grid { display: grid; gap: 20px; }

.season-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px 24px;
  box-shadow: var(--shadow);
}
.season-card h2 {
  font-size: 18px; margin-bottom: 14px; color: #5c3d2e;
  display: flex; align-items: center; gap: 8px;
}
.season-card h2 .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent); display: inline-block;
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

/* note page */
.meta-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 20px; margin-bottom: 32px;
  display: flex; flex-wrap: wrap; gap: 8px 24px; font-size: 13px;
  box-shadow: var(--shadow);
}
.meta-card .meta-item { display: flex; gap: 4px; }
.meta-card .meta-label { color: var(--muted); }
.meta-card .meta-value { color: var(--text); font-weight: 500; }

.content { font-size: 15px; }
.content h1 { font-size: 26px; margin: 32px 0 16px; color: #5c3d2e; }
.content h1:first-child { margin-top: 0; }
.content h2 {
  font-size: 20px; margin: 36px 0 12px; padding-bottom: 6px; color: #5c3d2e;
  border-bottom: 1px solid var(--border);
}
.content blockquote {
  background: var(--blockquote-bg);
  border-left: 3px solid var(--blockquote-border);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 12px 16px; margin: 12px 0;
  color: #5c3d2e; font-size: 14px;
}
.content blockquote strong { color: var(--accent); }
.content hr { border: none; border-top: 1px dashed var(--border); margin: 24px 0; }
.content p { margin: 8px 0; }

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
<title>BangumiBot · 观感记录</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<header>
  <h1><span>BangumiBot</span> 观感记录</h1>
  <p>{count} 个季度 · {anime_count} 部番剧</p>
</header>
{body}
<footer>BangumiBot — 追番管理 &amp; 观感记录</footer>
</div>
</body>
</html>"""

NOTE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 观感记录</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<div class="breadcrumb">
  <a href="/">观感记录</a> / {season_cn}
</div>
{meta_html}
<div class="content">
{body}
</div>
<footer>BangumiBot — 追番管理 &amp; 观感记录</footer>
</div>
</body>
</html>"""


def _render_meta(meta: dict) -> str:
    fields = []
    if meta.get("anime"):
        fields.append(("番剧", meta["anime"]))
    if meta.get("bangumi_subject_id"):
        fields.append(("Bangumi ID", str(meta["bangumi_subject_id"])))
    if meta.get("total_episodes"):
        fields.append(("总集数", str(meta["total_episodes"])))
    if meta.get("status"):
        fields.append(("状态", meta["status"]))
    if meta.get("started_at"):
        fields.append(("开始", meta["started_at"]))
    if not fields:
        return ""
    items = "\n".join(
        f'<div class="meta-item"><span class="meta-label">{k}:</span><span class="meta-value">{v}</span></div>'
        for k, v in fields
    )
    return f'<div class="meta-card">{items}</div>'


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, content.strip()


class WebViewer:
    def __init__(self, notes_dir: str, host: str = "0.0.0.0", port: int = 58080):
        self._notes_dir = Path(notes_dir)
        self._host = host
        self._port = port
        self._storage = MarkdownStorage(notes_dir)
        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._setup_routes()

    def _setup_routes(self):
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/notes/{season}/{anime}", self._handle_note)

    async def start(self):
        if self._port <= 0:
            logger.info("Web viewer disabled (port=0)")
            return
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(f"Web viewer started at http://{self._host}:{self._port}")

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            logger.info("Web viewer stopped")

    async def _handle_index(self, request: web.Request) -> web.Response:
        seasons = self._storage.list_seasons()
        if not seasons:
            html = INDEX_HTML.format(
                css=CSS, count=0, anime_count=0,
                body='<div class="empty">暂无观感记录。<br>开始追番后，观感记录会自动出现在这里。</div>',
            )
            return web.Response(text=html, content_type="text/html", charset="utf-8")

        cards = []
        total = 0
        for season in sorted(seasons, reverse=True):
            animes = self._storage.list_animes(season)
            total += len(animes)
            year, month = season.split(".")
            season_cn = f"{year}年{SEASON_NAMES.get(month, month)}季"
            links = "\n".join(
                f'<li><a href="/notes/{season}/{anime}">{anime}</a></li>'
                for anime in sorted(animes)
            )
            cards.append(
                f'<div class="season-card">'
                f'<h2><span class="dot"></span>{season_cn} <span style="color:var(--muted);font-size:13px;font-weight:400">({len(animes)}部)</span></h2>'
                f'<ul class="anime-list">{links}</ul>'
                f'</div>'
            )

        html = INDEX_HTML.format(
            css=CSS, count=len(seasons), anime_count=total,
            body="\n".join(cards),
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _handle_note(self, request: web.Request) -> web.Response:
        season = request.match_info["season"]
        anime = request.match_info["anime"]

        # 安全检查：防止路径遍历
        if ".." in season or ".." in anime:
            raise web.HTTPNotFound()

        content = self._storage.load_anime(anime, season)
        if content is None:
            raise web.HTTPNotFound()

        meta, body = _parse_frontmatter(content)
        html_body = markdown.markdown(
            body,
            extensions=["fenced_code", "tables", "codehilite"],
        )

        meta_html = _render_meta(meta)
        year, month = season.split(".")
        season_cn = f"{year}年{SEASON_NAMES.get(month, month)}季"
        title = meta.get("anime", anime)

        html = NOTE_HTML.format(
            css=CSS,
            title=title,
            season_cn=season_cn,
            meta_html=meta_html,
            body=html_body,
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")
