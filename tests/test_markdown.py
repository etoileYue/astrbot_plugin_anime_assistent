"""storage/markdown.py 单元测试。"""

import pytest

from storage.markdown import MarkdownStorage


# ---------------------------------------------------------------------------
# 测试辅助函数
# ---------------------------------------------------------------------------


def _make_storage(tmp_path) -> MarkdownStorage:
    """在临时目录中创建 MarkdownStorage 实例。"""
    return MarkdownStorage(str(tmp_path))


def _write_anime(storage: MarkdownStorage, anime_name: str, season: str,
                 subject_id: int = 0, total_eps: int = 0):
    """写入一个番剧的 Markdown 文件（空内容，仅 frontmatter）。"""
    season_dir = storage._base_dir / season
    season_dir.mkdir(parents=True, exist_ok=True)
    filename = storage._sanitize_filename(anime_name) + ".md"
    filepath = season_dir / filename

    frontmatter = (
        f"---\n"
        f"anime: {anime_name}\n"
        f"bangumi_subject_id: {subject_id}\n"
        f"season: {season}\n"
        f"total_episodes: {total_eps}\n"
        f"status: 在看\n"
        f"---\n\n"
        f"# {anime_name}\n"
    )
    filepath.write_text(frontmatter, encoding="utf-8")


def _add_episode(storage: MarkdownStorage, anime_name: str, season: str,
                 episode: int, qa_text: str = ""):
    """向已有番剧文件追加一个剧集章节。"""
    season_dir = storage._base_dir / season
    filename = storage._sanitize_filename(anime_name) + ".md"
    filepath = season_dir / filename

    if not qa_text:
        qa_text = f"> **Q1:** 测试问题{episode}\n>\n> **A1:** 测试回答{episode}\n\n"

    episode_section = f"\n## ep{episode:02d}\n\n{qa_text}"
    content = filepath.read_text(encoding="utf-8")
    content = content.rstrip() + episode_section
    filepath.write_text(content, encoding="utf-8")


def _add_rewatch(storage: MarkdownStorage, anime_name: str, season: str,
                 episode: int, qa_text: str = ""):
    """向已有番剧文件追加二刷章节（用 --- 分隔）。"""
    season_dir = storage._base_dir / season
    filename = storage._sanitize_filename(anime_name) + ".md"
    filepath = season_dir / filename

    if not qa_text:
        qa_text = f"> **Q1:** 二刷问题{episode}\n>\n> **A1:** 二刷回答{episode}\n\n"

    episode_section = f"\n## ep{episode:02d}\n\n{qa_text}"
    content = filepath.read_text(encoding="utf-8")
    content = content.rstrip() + f"\n---\n{episode_section}"
    filepath.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# delete_episode 测试
# ---------------------------------------------------------------------------


class TestDeleteEpisode:

    def test_delete_middle_episode(self, tmp_path):
        """删除中间的剧集，前后剧集保留。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "葬送的芙莉莲", "2026.4")
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 1)
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 2)
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 3)

        result = storage.delete_episode("葬送的芙莉莲", "2026.4", 2)
        assert result is True

        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## ep01" in content
        assert "## ep02" not in content
        assert "## ep03" in content

    def test_delete_first_episode(self, tmp_path):
        """删除第一集。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "药屋少女的呢喃", "2026.4")
        _add_episode(storage, "药屋少女的呢喃", "2026.4", 1)
        _add_episode(storage, "药屋少女的呢喃", "2026.4", 2)

        result = storage.delete_episode("药屋少女的呢喃", "2026.4", 1)
        assert result is True

        content = storage.load_anime("药屋少女的呢喃", "2026.4")
        assert "## ep01" not in content
        assert "## ep02" in content

    def test_delete_last_episode(self, tmp_path):
        """删除最后一集。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "鬼灭之刃", "2026.4")
        _add_episode(storage, "鬼灭之刃", "2026.4", 1)
        _add_episode(storage, "鬼灭之刃", "2026.4", 5)

        result = storage.delete_episode("鬼灭之刃", "2026.4", 5)
        assert result is True

        content = storage.load_anime("鬼灭之刃", "2026.4")
        assert "## ep01" in content
        assert "## ep05" not in content

    def test_delete_only_episode(self, tmp_path):
        """删除唯一的剧集，文件保留（仅剩 frontmatter + 标题）。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "咒术回战", "2026.4")
        _add_episode(storage, "咒术回战", "2026.4", 1)

        result = storage.delete_episode("咒术回战", "2026.4", 1)
        assert result is True

        content = storage.load_anime("咒术回战", "2026.4")
        assert content is not None
        assert "## ep01" not in content
        assert "咒术回战" in content  # 标题还在

    def test_delete_all_occurrences_with_rewatch(self, tmp_path):
        """有二次刷的集，删除应移除所有出现。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "上伊那牡丹", "2026.4")
        _add_episode(storage, "上伊那牡丹", "2026.4", 1)
        _add_rewatch(storage, "上伊那牡丹", "2026.4", 1)
        _add_episode(storage, "上伊那牡丹", "2026.4", 2)

        result = storage.delete_episode("上伊那牡丹", "2026.4", 1)
        assert result is True

        content = storage.load_anime("上伊那牡丹", "2026.4")
        assert "## ep01" not in content
        assert "## ep02" in content

    def test_delete_nonexistent_episode_returns_false(self, tmp_path):
        """删除不存在的剧集返回 False。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "葬送的芙莉莲", "2026.4")
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 1)

        result = storage.delete_episode("葬送的芙莉莲", "2026.4", 99)
        assert result is False

        # 文件内容不变
        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## ep01" in content

    def test_delete_nonexistent_file_returns_false(self, tmp_path):
        """文件不存在返回 False。"""
        storage = _make_storage(tmp_path)
        result = storage.delete_episode("不存在的番剧", "2026.4", 1)
        assert result is False


# ---------------------------------------------------------------------------
# append_to_episode 测试
# ---------------------------------------------------------------------------


class TestAppendToEpisode:

    def test_append_to_middle_episode(self, tmp_path):
        """向中间剧集追加笔记。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "葬送的芙莉莲", "2026.4")
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 1)
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 2)
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 3)

        result = storage.append_to_episode(
            "葬送的芙莉莲", "2026.4", 2, "追加的笔记内容"
        )
        assert result is True

        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "追加的笔记内容" in content
        assert "手动追加" in content
        # ep02 的内容应在 ep03 之前
        ep02_pos = content.find("## ep02")
        manual_pos = content.find("手动追加")
        ep03_pos = content.find("## ep03")
        assert ep02_pos < manual_pos < ep03_pos

    def test_append_to_last_episode(self, tmp_path):
        """向最后一集追加笔记。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "鬼灭之刃", "2026.4")
        _add_episode(storage, "鬼灭之刃", "2026.4", 1)
        _add_episode(storage, "鬼灭之刃", "2026.4", 5)

        result = storage.append_to_episode(
            "鬼灭之刃", "2026.4", 5, "结尾追加"
        )
        assert result is True

        content = storage.load_anime("鬼灭之刃", "2026.4")
        assert "结尾追加" in content
        assert "手动追加" in content

    def test_append_to_rewatch_appends_to_last_occurrence(self, tmp_path):
        """有二刷时，追加应到该集的最后一次出现。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "上伊那牡丹", "2026.4")
        _add_episode(storage, "上伊那牡丹", "2026.4", 1)
        _add_rewatch(storage, "上伊那牡丹", "2026.4", 1)
        _add_episode(storage, "上伊那牡丹", "2026.4", 2)

        result = storage.append_to_episode(
            "上伊那牡丹", "2026.4", 1, "二刷后的追加"
        )
        assert result is True

        content = storage.load_anime("上伊那牡丹", "2026.4")
        # 追加内容应在二刷部分，ep02 之前
        rewatch_pos = content.find("二刷")
        manual_pos = content.rfind("手动追加")
        ep02_pos = content.find("## ep02")
        assert manual_pos > rewatch_pos  # 追加在二刷之后
        assert manual_pos < ep02_pos     # 追加在 ep02 之前

    def test_append_nonexistent_episode_returns_false(self, tmp_path):
        """剧集不存在返回 False。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "葬送的芙莉莲", "2026.4")
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 1)

        result = storage.append_to_episode(
            "葬送的芙莉莲", "2026.4", 99, "对不存在的集追加"
        )
        assert result is False

    def test_append_nonexistent_file_returns_false(self, tmp_path):
        """文件不存在返回 False。"""
        storage = _make_storage(tmp_path)
        result = storage.append_to_episode(
            "不存在的番剧", "2026.4", 1, "追加内容"
        )
        assert result is False

    def test_append_preserves_summary_section(self, tmp_path):
        """追加笔记不影响 ## 总结 章节。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "葬送的芙莉莲", "2026.4")
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 1)
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 2)

        # 先添加总结
        storage.append_summary("葬送的芙莉莲", "2026.4", "这是一部好番剧")

        # 再追加笔记到 ep02
        result = storage.append_to_episode(
            "葬送的芙莉莲", "2026.4", 2, "ep02 的追加笔记"
        )
        assert result is True

        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## 总结" in content
        assert "这是一部好番剧" in content
        assert "ep02 的追加笔记" in content
        # 总结章节在追加内容之后
        summary_pos = content.find("## 总结")
        manual_pos = content.find("ep02 的追加笔记")
        assert manual_pos < summary_pos


# ---------------------------------------------------------------------------
# 往返测试
# ---------------------------------------------------------------------------


class TestRoundtrip:

    def test_save_then_delete(self, tmp_path):
        """先保存再删除的往返测试。"""
        storage = _make_storage(tmp_path)

        storage.save_episode(
            anime_name="葬送的芙莉莲",
            season="2026.4",
            episode=7,
            qa_pairs=[("测试问题", "测试回答")],
            subject_id=400602,
        )

        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## ep07" in content

        result = storage.delete_episode("葬送的芙莉莲", "2026.4", 7)
        assert result is True

        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## ep07" not in content

    def test_save_then_append(self, tmp_path):
        """先保存再追加的往返测试。"""
        storage = _make_storage(tmp_path)

        storage.save_episode(
            anime_name="药屋少女的呢喃",
            season="2026.4",
            episode=3,
            qa_pairs=[("问题", "回答")],
            subject_id=999999,
        )

        result = storage.append_to_episode(
            "药屋少女的呢喃", "2026.4", 3, "手动追加的内容"
        )
        assert result is True

        content = storage.load_anime("药屋少女的呢喃", "2026.4")
        assert "## ep03" in content
        assert "手动追加" in content
        assert "回答" in content  # 原始内容还在

    def test_save_rewatch_then_delete(self, tmp_path):
        """保存后二刷，再删除——全部移除。"""
        storage = _make_storage(tmp_path)

        storage.save_episode(
            anime_name="上伊那牡丹",
            season="2026.4",
            episode=1,
            qa_pairs=[("初刷问题", "初刷回答")],
        )

        # 模拟二刷：直接追加 section
        _add_rewatch(storage, "上伊那牡丹", "2026.4", 1,
                     qa_text="> **Q1:** 二刷问题\n>\n> **A1:** 二刷回答\n\n")

        content = storage.load_anime("上伊那牡丹", "2026.4")
        assert "初刷" in content
        assert "二刷" in content

        result = storage.delete_episode("上伊那牡丹", "2026.4", 1)
        assert result is True

        content = storage.load_anime("上伊那牡丹", "2026.4")
        assert "初刷" not in content
        assert "二刷" not in content
        assert "## ep01" not in content


# ---------------------------------------------------------------------------
# save_anime 测试
# ---------------------------------------------------------------------------


class TestSaveAnime:

    def test_save_new_file(self, tmp_path):
        """保存新文件——目录不存在时自动创建。"""
        storage = _make_storage(tmp_path)

        content = "---\nanime: 测试番剧\n---\n\n# 测试番剧\n\n## ep01\n\n测试内容\n"
        result = storage.save_anime("测试番剧", "2026.4", content)
        assert result is True

        loaded = storage.load_anime("测试番剧", "2026.4")
        assert loaded == content

    def test_save_overwrites_existing(self, tmp_path):
        """保存覆盖已有文件。"""
        storage = _make_storage(tmp_path)
        _write_anime(storage, "葬送的芙莉莲", "2026.4")
        _add_episode(storage, "葬送的芙莉莲", "2026.4", 1)

        original = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## ep01" in original

        new_content = "---\nanime: 葬送的芙莉莲\n---\n\n# 葬送的芙莉莲\n\n修改后的内容\n"
        result = storage.save_anime("葬送的芙莉莲", "2026.4", new_content)
        assert result is True

        loaded = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert loaded == new_content
        assert "## ep01" not in loaded

    def test_save_edit_then_view_roundtrip(self, tmp_path):
        """模拟编辑流程：创建 → 编辑 → 验证。"""
        storage = _make_storage(tmp_path)

        # 先通过正常流程创建
        storage.save_episode(
            anime_name="葬送的芙莉莲",
            season="2026.4",
            episode=1,
            qa_pairs=[("Q1", "A1")],
            subject_id=400602,
        )

        # 加载全文
        content = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "## ep01" in content
        assert "Q1" in content

        # 模拟编辑：修改内容
        edited = content.replace("A1", "编辑后的回答")
        edited += "\n## ep02\n\n> **Q1:** 新问题\n>\n> **A1:** 新回答\n\n"

        result = storage.save_anime("葬送的芙莉莲", "2026.4", edited)
        assert result is True

        # 验证编辑结果
        loaded = storage.load_anime("葬送的芙莉莲", "2026.4")
        assert "编辑后的回答" in loaded
        assert "## ep02" in loaded
        assert "新问题" in loaded


# ---------------------------------------------------------------------------
# 路径操作方法测试（WebEditor 文件管理）
# ---------------------------------------------------------------------------


class TestPathMethods:

    def test_resolve_path_normal(self, tmp_path):
        """正常路径解析。"""
        storage = _make_storage(tmp_path)
        resolved = storage._resolve_path("2026.4/test.md")
        assert resolved == tmp_path / "2026.4" / "test.md"

    def test_resolve_path_traversal_denied(self, tmp_path):
        """拒绝 .. 路径遍历。"""
        storage = _make_storage(tmp_path)
        with pytest.raises(ValueError, match="traversal"):
            storage._resolve_path("../../../etc/passwd")

    def test_resolve_path_absolute_stripped(self, tmp_path):
        """绝对路径前缀被剥离，解析到 base_dir 下。"""
        storage = _make_storage(tmp_path)
        resolved = storage._resolve_path("/2026.4/test.md")
        assert resolved == tmp_path / "2026.4" / "test.md"

    def test_list_directory_empty(self, tmp_path):
        """空目录返回空列表。"""
        storage = _make_storage(tmp_path)
        result = storage.list_directory("")
        assert result == {"dirs": [], "files": []}

    def test_list_directory_with_content(self, tmp_path):
        """列出目录中的文件和子目录。"""
        storage = _make_storage(tmp_path)
        storage.save_file("a.md", "content a")
        storage.save_file("b.md", "content b")
        storage.create_directory("", "subdir")

        result = storage.list_directory("")
        assert result["dirs"] == ["subdir"]
        assert result["files"] == ["a.md", "b.md"]

    def test_list_directory_filters_non_md(self, tmp_path):
        """只列出 .md 文件，其他文件被忽略。"""
        storage = _make_storage(tmp_path)
        storage.save_file("note.md", "markdown")
        # 创建一个非 .md 文件
        (storage._base_dir / "data.txt").write_text("text")
        (storage._base_dir / "image.png").write_text("png", encoding="utf-8")

        result = storage.list_directory("")
        assert result["files"] == ["note.md"]
        # data.txt 和 image.png 不会被列出

    def test_list_subdirectory(self, tmp_path):
        """列出子目录内容。"""
        storage = _make_storage(tmp_path)
        storage.save_file("2026.4/a.md", "a")
        storage.save_file("2026.4/b.md", "b")
        storage.create_directory("2026.4", "sub")

        result = storage.list_directory("2026.4")
        assert result["dirs"] == ["sub"]
        assert result["files"] == ["a.md", "b.md"]

    def test_load_file_exists(self, tmp_path):
        """加载存在的文件。"""
        storage = _make_storage(tmp_path)
        storage.save_file("test.md", "hello world")
        content = storage.load_file("test.md")
        assert content == "hello world"

    def test_load_file_not_exists(self, tmp_path):
        """加载不存在的文件返回 None。"""
        storage = _make_storage(tmp_path)
        assert storage.load_file("nonexistent.md") is None

    def test_save_file_new(self, tmp_path):
        """保存新文件，自动创建父目录。"""
        storage = _make_storage(tmp_path)
        result = storage.save_file("sub/dir/file.md", "content")
        assert result is True
        loaded = storage.load_file("sub/dir/file.md")
        assert loaded == "content"

    def test_save_file_overwrite(self, tmp_path):
        """覆盖已有文件。"""
        storage = _make_storage(tmp_path)
        storage.save_file("test.md", "original")
        storage.save_file("test.md", "modified")
        assert storage.load_file("test.md") == "modified"

    def test_create_file_success(self, tmp_path):
        """成功创建新文件。"""
        storage = _make_storage(tmp_path)
        ok, path = storage.create_file("", "新笔记")
        assert ok is True
        assert path == "新笔记.md"
        assert storage.load_file("新笔记.md") == ""
        assert (storage._base_dir / "新笔记.md").exists()

    def test_create_file_in_subdir(self, tmp_path):
        """在子目录中创建文件。"""
        storage = _make_storage(tmp_path)
        storage.create_directory("", "diary")

        ok, path = storage.create_file("diary", "我的日记")
        assert ok is True
        assert path == "diary/我的日记.md"
        assert storage.load_file("diary/我的日记.md") == ""

    def test_create_file_already_exists(self, tmp_path):
        """文件已存在时创建失败。"""
        storage = _make_storage(tmp_path)
        storage.create_file("", "note")
        ok, msg = storage.create_file("", "note")
        assert ok is False
        assert "已存在" in msg

    def test_create_directory_success(self, tmp_path):
        """成功创建目录。"""
        storage = _make_storage(tmp_path)
        ok, path = storage.create_directory("", "new-folder")
        assert ok is True
        assert path == "new-folder"
        assert (storage._base_dir / "new-folder").is_dir()

    def test_create_directory_nested(self, tmp_path):
        """创建嵌套目录。"""
        storage = _make_storage(tmp_path)
        storage.create_directory("", "a")
        ok, path = storage.create_directory("a", "b")
        assert ok is True
        assert path == "a/b"
        assert (storage._base_dir / "a" / "b").is_dir()

    def test_create_directory_already_exists(self, tmp_path):
        """目录已存在时创建失败。"""
        storage = _make_storage(tmp_path)
        storage.create_directory("", "existing")
        ok, msg = storage.create_directory("", "existing")
        assert ok is False
        assert "已存在" in msg

    def test_delete_file(self, tmp_path):
        """删除文件。"""
        storage = _make_storage(tmp_path)
        storage.save_file("remove.md", "to be deleted")
        assert (storage._base_dir / "remove.md").exists()

        ok, msg = storage.delete_path("remove.md")
        assert ok is True
        assert "已删除" in msg
        assert not (storage._base_dir / "remove.md").exists()

    def test_delete_empty_dir(self, tmp_path):
        """删除空目录。"""
        storage = _make_storage(tmp_path)
        storage.create_directory("", "empty-dir")

        ok, msg = storage.delete_path("empty-dir")
        assert ok is True
        assert not (storage._base_dir / "empty-dir").exists()

    def test_delete_nonempty_dir_denied(self, tmp_path):
        """非空目录拒绝删除。"""
        storage = _make_storage(tmp_path)
        storage.save_file("nonempty/file.md", "content")

        ok, msg = storage.delete_path("nonempty")
        assert ok is False
        assert "非空" in msg
        assert (storage._base_dir / "nonempty").exists()

    def test_delete_nonexistent(self, tmp_path):
        """删除不存在的路径。"""
        storage = _make_storage(tmp_path)
        ok, msg = storage.delete_path("does-not-exist.md")
        assert ok is False
        assert "不存在" in msg
