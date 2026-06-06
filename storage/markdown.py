"""Markdown 存储 — Obsidian 兼容的观感记录读写。"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 文件名不允许的字符
_SANITIZE_TABLE = str.maketrans({
    "/": "／", ":": "：", "?": "？", "*": "＊",
    "\"": "＂", "<": "＜", ">": "＞", "|": "｜",
    "\\": "＼",
})


class MarkdownStorage:
    def __init__(self, base_dir: str = "anime_notes"):
        self._base_dir = Path(base_dir)

    @staticmethod
    def _get_season_dir(air_date: str) -> str:
        """根据首播日期计算季度目录名。"""
        if not air_date:
            return "unknown"
        month = int(air_date.split("-")[1])
        year = air_date.split("-")[0]
        if month <= 3:
            return f"{year}.1"
        elif month <= 6:
            return f"{year}.4"
        elif month <= 9:
            return f"{year}.7"
        else:
            return f"{year}.10"

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        return name.translate(_SANITIZE_TABLE).strip()

    def save_episode(
        self,
        anime_name: str,
        season: str,
        episode: int,
        qa_pairs: list[tuple[str, str]],
        subject_id: int = 0,
        total_episodes: int = 0,
    ) -> str:
        """保存单集观感到对应番剧文件，返回文件路径。"""
        season_dir = self._base_dir / season
        season_dir.mkdir(parents=True, exist_ok=True)
        filename = self._sanitize_filename(anime_name) + ".md"
        filepath = season_dir / filename

        episode_section = f"\n## ep{episode:02d}\n\n"
        for i, (q, a) in enumerate(qa_pairs, 1):
            episode_section += f"> **Q{i}:** {q}\n>\n"
            if a:
                episode_section += f"> **A{i}:** {a}\n\n"
            else:
                episode_section += f"> **A{i}:** \n\n"

        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            if f"## ep{episode:02d}" in content:
                # 同集追加，用分隔线
                content = content.rstrip()
                content += f"\n---\n{episode_section}"
            else:
                content = content.rstrip()
                content += episode_section
            filepath.write_text(content, encoding="utf-8")
        else:
            frontmatter = (
                f"---\n"
                f"anime: {anime_name}\n"
                f"bangumi_subject_id: {subject_id}\n"
                f"season: {season}\n"
                f"total_episodes: {total_episodes}\n"
                f"status: 在看\n"
                f"---\n\n"
                f"# {anime_name}\n"
            )
            filepath.write_text(frontmatter + episode_section, encoding="utf-8")

        logger.info(f"Saved episode to {filepath}")
        return str(filepath)

    def load_anime(self, anime_name: str, season: str) -> str | None:
        season_dir = self._base_dir / season
        filename = self._sanitize_filename(anime_name) + ".md"
        filepath = season_dir / filename
        if not filepath.exists():
            return None
        return filepath.read_text(encoding="utf-8")

    def load_episode(self, anime_name: str, season: str, episode: int) -> str | None:
        content = self.load_anime(anime_name, season)
        if not content:
            return None
        marker = f"## ep{episode:02d}"
        if marker not in content:
            return None
        # 找到该集 section
        sections = content.split("## ")
        for sec in sections:
            if sec.startswith(f"ep{episode:02d}"):
                return "## " + sec.split("---")[0].strip()
        return None

    def list_seasons(self) -> list[str]:
        if not self._base_dir.exists():
            return []
        return [d.name for d in self._base_dir.iterdir() if d.is_dir()]

    def list_animes(self, season: str) -> list[str]:
        season_dir = self._base_dir / season
        if not season_dir.exists():
            return []
        return [p.stem for p in season_dir.glob("*.md")]

    def append_summary(self, anime_name: str, season: str, summary: str):
        content = self.load_anime(anime_name, season)
        if content is None:
            return
        season_dir = self._base_dir / season
        filename = self._sanitize_filename(anime_name) + ".md"
        filepath = season_dir / filename
        summary_section = f"\n## 总结\n\n{summary}\n"
        if "## 总结" in content:
            parts = content.split("## 总结")
            content = parts[0] + summary_section
        else:
            content = content.rstrip() + "\n" + summary_section
        filepath.write_text(content, encoding="utf-8")
