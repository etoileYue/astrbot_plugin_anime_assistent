#!/usr/bin/env python3
"""本地开发服务器 — 在本地预览 WebViewer + WebEditor，无需部署到服务器。

用法:
    python tools/dev_server.py              # 启动服务器（不自动重载）
    python tools/dev_server.py --reload     # 文件变更时自动重启（需安装 watchfiles）

依赖（均已包含在 requirements.txt 中）:
    pip install aiohttp pyyaml markdown

端口:
    58080 — WebViewer（只读查看）
    58081 — WebEditor（文件管理 + 编辑）
"""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _setup_path():
    """将项目根目录的父目录加入 sys.path，使包导入工作正常。"""
    project_dir = Path(__file__).resolve().parent.parent
    parent = str(project_dir.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)


def _create_sample_data(notes_dir: str):
    """在指定目录中创建示例番剧笔记，方便开发时预览效果。"""
    from astrbot_plugin_anime_assistent.storage.markdown import MarkdownStorage

    storage = MarkdownStorage(notes_dir)

    samples = {
        "2026.4": [
            (
                "葬送的芙莉莲",
                """---
anime: 葬送的芙莉莲
bangumi_subject_id: 400602
season: 2026.4
total_episodes: 28
status: 在看
---

# 葬送的芙莉莲

## ep01

> **Q1:** 第一集的开场给你留下了什么印象？
>
> **A1:** 很喜欢这种娓娓道来的叙事节奏。芙莉莲在辛美尔葬礼上的独白特别动人，她终于开始理解人类的时间观念了。

> **Q2:** 你觉得本集最打动你的场景是什么？
>
> **A2:** 芙莉莲看到流星的那个瞬间，她想起了和辛美尔一行人的约定。时间跨越了五十年，但记忆依然清晰。

## ep02

> **Q1:** 芙莉莲收下菲伦作为弟子，你怎么看这个决定？
>
> **A1:** 很有趣的化学反应。菲伦是个务实的孩子，和芙莉莲的随性形成了对比，但也让旅途多了很多温馨的时刻。
""",
            ),
            (
                "药屋少女的呢喃",
                """---
anime: 药屋少女的呢喃
bangumi_subject_id: 999999
season: 2026.4
total_episodes: 24
status: 在看
---

# 药屋少女的呢喃

## ep01

> **Q1:** 猫猫这个角色给你留下了什么印象？
>
> **A1:** 非常聪明且独立。她对毒药的痴迷让人又好笑又有点害怕，但她本质上是个善良的人。

> **Q2:** 壬氏和猫猫的初次相遇场景怎么样？
>
> **A2:** 很有意思！猫猫完全不为壬氏的美貌所动，反而对他的药产生了兴趣。这种反差很有趣。

## ep02

> **Q1:** 本集的案件设计得如何？
>
> **A1:** 很好地把医药知识和推理结合在了一起。猫猫的观察力确实出色。

## ep03

> **Q1:** 后宫里的权力斗争描写得怎么样？
>
> **A1:** 比想象中有深度。不单是争风吃醋，而是各有各的生存策略。
""",
            ),
        ],
        "2026.1": [
            (
                "上伊那牡丹",
                """---
anime: 上伊那牡丹
bangumi_subject_id: 888888
season: 2026.1
total_episodes: 12
status: 看过
---

# 上伊那牡丹

## ep01

> **Q1:** 第一集看完有什么感受？
>
> **A1:** 画风很清新，牡丹的性格塑造得很有趣。虽然是个小酒吧的场景，但人情味很浓。

## ep12

> **Q1:** 最终回给你留下了什么感触？
>
> **A1:** 很温暖的结局。牡丹终于找到了自己想要的生活方式，和朋友们的羁绊也更加深厚了。

## 总结

上伊那牡丹是一部很舒服的日常番，适合在下班后放松心情时观看。每一集都有恰到好处的温情和幽默。
""",
            ),
        ],
    }

    for season, animes in samples.items():
        for name, content in animes:
            storage.save_anime(name, season, content)

    print(f"  示例数据已创建: {len(samples)} 个季度, "
          f"{sum(len(a) for a in samples.values())} 部番剧")


async def _run_servers(notes_dir: str, viewer_port: int, editor_port: int):
    """启动 View 和 Edit 两个 Web 服务。"""
    from astrbot_plugin_anime_assistent.core.web_viewer import WebViewer
    from astrbot_plugin_anime_assistent.core.web_editor import WebEditor

    viewer = WebViewer(notes_dir, port=viewer_port)
    editor = WebEditor(notes_dir, port=editor_port)

    await viewer.start()
    await editor.start()

    print()
    print("─" * 56)
    print(f"  📖 WebViewer   http://localhost:{viewer_port}")
    print(f"     （只读查看，分享给他人用这个地址）")
    print(f"  ✏️  WebEditor   http://localhost:{editor_port}")
    print(f"     （文件管理 + 编辑，自己用这个地址）")
    print("─" * 56)
    print("  按 Ctrl+C 停止服务器")
    print()

    # 等待中断信号
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def _on_signal():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass

    print("\n正在停止服务器...")
    await editor.stop()
    await viewer.stop()
    print("已停止。")


def main():
    parser = argparse.ArgumentParser(description="BangumiBot 本地开发服务器")
    parser.add_argument(
        "--viewer-port", type=int, default=58080, help="查看器端口（默认 58080）"
    )
    parser.add_argument(
        "--editor-port", type=int, default=58081, help="编辑器端口（默认 58081）"
    )
    parser.add_argument(
        "--reload", action="store_true", help="文件变更时自动重启（需安装 watchfiles）"
    )
    parser.add_argument(
        "--no-sample", action="store_true", help="不创建示例数据"
    )
    args = parser.parse_args()

    if args.reload:
        _run_with_reload(args)
    else:
        _run_once(args)


def _run_once(args):
    """单次启动（无自动重载）。"""
    _setup_path()

    with TemporaryDirectory(prefix="bangumi_notes_") as tmp_dir:
        notes_dir = str(Path(tmp_dir) / "anime_notes")

        if not args.no_sample:
            _create_sample_data(notes_dir)
        else:
            os.makedirs(notes_dir, exist_ok=True)

        try:
            asyncio.run(_run_servers(notes_dir, args.viewer_port, args.editor_port))
        except KeyboardInterrupt:
            pass


def _run_with_reload(args):
    """使用 watchfiles 实现自动重载。"""
    try:
        import watchfiles  # noqa: F401
    except ImportError:
        print("错误: --reload 需要安装 watchfiles")
        print("  pip install watchfiles")
        sys.exit(1)

    _setup_path()
    project_dir = Path(__file__).resolve().parent.parent

    print(f"🔁 自动重载模式：监视 {project_dir}")
    print("   修改 Python/CSS 文件后自动重启\n")

    # 将参数传递给子进程
    import subprocess

    script = Path(__file__).resolve()
    cmd = [
        sys.executable, str(script),
        "--viewer-port", str(args.viewer_port),
        "--editor-port", str(args.editor_port),
    ]
    if args.no_sample:
        cmd.append("--no-sample")

    # 使用 watchfiles 的 run_process
    from watchfiles import run_process

    run_process(
        str(project_dir),
        target=lambda: subprocess.run(cmd),
        watch_filter=lambda change, path: (
            path.endswith(".py") or path.endswith(".css") or path.endswith(".html")
        ),
        debounce=800,
    )


if __name__ == "__main__":
    main()
