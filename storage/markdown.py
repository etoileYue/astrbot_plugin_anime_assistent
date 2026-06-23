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

    def delete_episode(self, anime_name: str, season: str, episode: int) -> bool:
        """删除指定剧集的所有观感记录（包括二刷）。

        返回 True 表示成功删除，False 表示文件或剧集不存在。
        """
        content = self.load_anime(anime_name, season)
        if content is None:
            return False

        sections = content.split("## ")
        filtered = [s for s in sections if not s.startswith(f"ep{episode:02d}")]

        if len(filtered) == len(sections):
            return False

        season_dir = self._base_dir / season
        filename = self._sanitize_filename(anime_name) + ".md"
        filepath = season_dir / filename
        filepath.write_text("## ".join(filtered), encoding="utf-8")
        logger.info(f"Deleted episode {episode} from {filepath}")
        return True

    def append_to_episode(self, anime_name: str, season: str,
                          episode: int, text: str) -> bool:
        """在指定剧集最后一次记录末尾追加手动笔记。

        返回 True 表示成功追加，False 表示文件或剧集不存在。
        """
        content = self.load_anime(anime_name, season)
        if content is None:
            return False

        sections = content.split("## ")
        last_idx = None
        for i, sec in enumerate(sections):
            if sec.startswith(f"ep{episode:02d}"):
                last_idx = i

        if last_idx is None:
            return False

        sections[last_idx] += f"\n\n> **手动追加:** {text}\n"

        season_dir = self._base_dir / season
        filename = self._sanitize_filename(anime_name) + ".md"
        filepath = season_dir / filename
        filepath.write_text("## ".join(sections), encoding="utf-8")
        logger.info(f"Appended note to episode {episode} in {filepath}")
        return True

    def save_anime(self, anime_name: str, season: str, content: str) -> bool:
        """全量覆盖番剧 Markdown 文件。

        用于编辑器全文本保存。目录不存在时自动创建。
        始终返回 True（写入操作不会失败，除非磁盘满了）。
        """
        season_dir = self._base_dir / season
        season_dir.mkdir(parents=True, exist_ok=True)
        filename = self._sanitize_filename(anime_name) + ".md"
        filepath = season_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved full file: {filepath}")
        return True

    # ------------------------------------------------------------------
    # 路径操作方法 — 基于相对路径，用于 WebEditor 文件管理
    # ------------------------------------------------------------------

    def _resolve_path(self, sub_path: str) -> Path:
        """将相对路径解析为绝对路径，并检查路径遍历攻击。

        Raises:
            ValueError: 路径尝试逃逸 base_dir 时抛出。
        """
        # 清理路径中的危险片段
        cleaned = sub_path.replace("\\", "/")
        if cleaned.startswith("/"):
            cleaned = cleaned.lstrip("/")

        resolved = (self._base_dir / cleaned).resolve()
        if not str(resolved).startswith(str(self._base_dir.resolve())):
            raise ValueError(f"Path traversal denied: {sub_path}")
        return resolved

    def list_directory(self, sub_path: str = "") -> dict:
        """列出子目录下的文件和文件夹（仅 .md 文件）。

        Returns:
            {"dirs": [name, ...], "files": [name, ...]}，均按名称排序。
        """
        target = self._resolve_path(sub_path) if sub_path else self._base_dir
        if not target.exists():
            return {"dirs": [], "files": []}

        dirs = sorted(
            [d.name for d in target.iterdir() if d.is_dir()],
            key=str.lower,
        )
        files = sorted(
            [p.name for p in target.glob("*.md")],
            key=str.lower,
        )
        return {"dirs": dirs, "files": files}

    def load_file(self, sub_path: str) -> str | None:
        """通过相对路径加载文件内容。"""
        try:
            filepath = self._resolve_path(sub_path)
        except ValueError:
            return None
        if not filepath.exists() or not filepath.is_file():
            return None
        return filepath.read_text(encoding="utf-8")

    def save_file(self, sub_path: str, content: str) -> bool:
        """覆盖写入文件内容。父目录不存在时自动创建。"""
        try:
            filepath = self._resolve_path(sub_path)
        except ValueError:
            return False
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved file: {filepath}")
        return True

    def create_file(self, parent_path: str, filename: str,
                    content: str = "") -> tuple[bool, str]:
        """在指定目录下创建新的 .md 文件。

        Args:
            parent_path: 父目录相对路径（空字符串表示根目录）。
            filename: 文件名（自动添加 .md 扩展名，不含扩展名时）。

        Returns:
            (True, relative_path) 成功时； (False, error_message) 失败时。
        """
        if not filename.endswith(".md"):
            filename += ".md"
        filename = self._sanitize_filename(filename)

        try:
            parent = self._resolve_path(parent_path) if parent_path else self._base_dir
        except ValueError:
            return False, "无效的目录路径"
        parent.mkdir(parents=True, exist_ok=True)

        filepath = parent / filename
        if filepath.exists():
            return False, f"文件 {filename} 已存在"

        filepath.write_text(content or "", encoding="utf-8")
        # 返回相对于 base_dir 的路径
        rel = str(filepath.relative_to(self._base_dir))
        logger.info(f"Created file: {rel}")
        return True, rel

    def create_directory(self, parent_path: str, dirname: str) -> tuple[bool, str]:
        """在指定目录下创建子目录。

        Returns:
            (True, relative_path) 成功时； (False, error_message) 失败时。
        """
        dirname = self._sanitize_filename(dirname)

        try:
            parent = self._resolve_path(parent_path) if parent_path else self._base_dir
        except ValueError:
            return False, "无效的目录路径"
        parent.mkdir(parents=True, exist_ok=True)

        dirpath = parent / dirname
        if dirpath.exists():
            return False, f"目录 {dirname} 已存在"

        dirpath.mkdir()
        rel = str(dirpath.relative_to(self._base_dir))
        logger.info(f"Created directory: {rel}")
        return True, rel

    def delete_path(self, sub_path: str) -> tuple[bool, str]:
        """删除文件或空目录。

        Returns:
            (True, success_message) 成功时； (False, error_message) 失败时。
        """
        try:
            target = self._resolve_path(sub_path)
        except ValueError:
            return False, "无效的路径"

        if not target.exists():
            return False, "文件或目录不存在"

        if target.is_dir():
            try:
                target.rmdir()  # 只删除空目录
                logger.info(f"Deleted directory: {sub_path}")
                return True, f"已删除目录 {target.name}"
            except OSError:
                return False, f"目录 {target.name} 非空，无法删除"
        else:
            target.unlink()
            logger.info(f"Deleted file: {sub_path}")
            return True, f"已删除文件 {target.name}"
