"""WebEditor 下载接口及页面入口测试，无需 AstrBot 或 pytest-asyncio。"""

import asyncio
import sys
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_anime_assistent.core.web_editor import WebEditor


def _get(editor, path, *, params=None):
    async def run():
        async with TestClient(TestServer(editor._app)) as client:
            async with client.get(path, params=params) as response:
                return (
                    response.status,
                    response.headers,
                    response.content_disposition,
                    await response.read(),
                )

    return asyncio.run(run())


@pytest.mark.parametrize("content", [b"", "\ufeff---\r\nanime: 芙莉莲\r\n---\r\n# 观感\r\n".encode("utf-8")])
@pytest.mark.parametrize("filename", ["note.md", '芙莉莲 & "引号" # + %.md'])
def test_export_download_preserves_bytes_and_filename(tmp_path, content, filename):
    directory = tmp_path / "2026.4"
    directory.mkdir()
    target = directory / filename
    target.write_bytes(content)
    editor = WebEditor(str(tmp_path))

    status, headers, disposition, body = _get(
        editor, "/api/export", params={"path": f"2026.4/{filename}"},
    )

    assert status == 200
    assert headers["Content-Type"] == "text/markdown; charset=utf-8"
    assert disposition.type == "attachment"
    assert disposition.filename == filename
    assert body == content
    assert target.read_bytes() == content


@pytest.mark.parametrize("path", [None, "", "../private.md", "/private.md", "dir\\note.md", "data.txt", "\x00.md"])
def test_export_rejects_invalid_paths(tmp_path, path):
    editor = WebEditor(str(tmp_path))
    status, _, _, body = _get(
        editor, "/api/export", params={} if path is None else {"path": path},
    )
    assert status == 400
    assert body.decode("utf-8")


@pytest.mark.parametrize("path", ["missing.md", "directory.md"])
def test_export_missing_file_or_directory_returns_404(tmp_path, path):
    (tmp_path / "directory.md").mkdir()
    status, _, _, body = _get(WebEditor(str(tmp_path)), "/api/export", params={"path": path})
    assert status == 404
    assert body.decode("utf-8") == "笔记文件不存在"


@pytest.mark.parametrize("link_kind", ["file", "directory"])
def test_export_rejects_symlink_to_sibling_with_same_prefix(tmp_path, link_kind):
    base = tmp_path / "notes"
    base.mkdir()
    sibling = tmp_path / "notes-backup"
    sibling.mkdir()
    (sibling / "private.md").write_bytes(b"private")
    if link_kind == "file":
        (base / "link.md").symlink_to(sibling / "private.md")
        path = "link.md"
    else:
        (base / "linked").symlink_to(sibling, target_is_directory=True)
        path = "linked/private.md"

    status, _, _, body = _get(WebEditor(str(base)), "/api/export", params={"path": path})
    assert status == 400
    assert b"private" not in body


def test_export_all_downloads_zip(tmp_path):
    editor = WebEditor(str(tmp_path))
    editor._storage.save_file("root.md", "root")
    editor._storage.save_file("季度/芙莉莲.md", "观感")
    (tmp_path / "image.png").write_bytes(b"not a note")

    status, headers, disposition, body = _get(editor, "/api/export-all")

    assert status == 200
    assert headers["Content-Type"] == "application/zip"
    assert disposition.type == "attachment"
    assert disposition.filename == "bangumibot-notes.zip"
    with ZipFile(BytesIO(body)) as archive:
        assert set(archive.namelist()) == {"root.md", "季度/芙莉莲.md"}
        assert archive.read("季度/芙莉莲.md") == "观感".encode("utf-8")


@pytest.mark.parametrize("create_directory", [True, False])
def test_export_all_without_notes_returns_404(tmp_path, create_directory):
    base = tmp_path / "notes"
    if create_directory:
        base.mkdir()
    status, _, _, body = _get(WebEditor(str(base)), "/api/export-all")
    assert status == 404
    assert "暂无可导出的笔记" in body.decode("utf-8")


@pytest.mark.parametrize("endpoint,method,params", [
    ("/api/export", "read_note_bytes", {"path": "note.md"}),
    ("/api/export-all", "export_notes_zip", None),
])
def test_export_io_failure_returns_chinese_error(tmp_path, monkeypatch, endpoint, method, params):
    editor = WebEditor(str(tmp_path))

    def fail(*args):
        raise PermissionError("private server path")

    monkeypatch.setattr(editor._storage, method, fail)
    status, headers, _, body = _get(editor, endpoint, params=params)
    assert status == 500
    assert "Content-Disposition" not in headers
    assert body.decode("utf-8") == "导出失败，请稍后重试"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.downloads = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "download" in attrs:
            self.downloads.append(attrs["href"])


def test_page_download_links_use_saved_content_without_submitting_form(tmp_path):
    path = '2026.4/芙莉莲 & "引号" # + %.md'
    editor = WebEditor(str(tmp_path))
    editor._storage.save_file(path, "已保存的观感")

    async def run():
        async with TestClient(TestServer(editor._app)) as client:
            async with client.get("/", params={"path": path}) as response:
                assert response.status == 200
                page = await response.text()
            links = _Links()
            links.feed(page)
            assert "/api/export-all" in links.downloads
            single = next(link for link in links.downloads if link.startswith("/api/export?"))
            assert parse_qs(urlsplit(single).query) == {"path": [path]}
            assert "导出当前笔记" in page
            assert "导出已保存版本，修改后请先保存" in page
            # 额外的草稿参数不能覆盖服务器上的文件或下载内容。
            async with client.get(single, params={"content": "未保存的修改"}) as response:
                assert response.status == 200
                assert await response.read() == "已保存的观感".encode("utf-8")
            assert editor._storage.load_file(path) == "已保存的观感"

    asyncio.run(run())


def test_empty_home_page_includes_export_all_link(tmp_path):
    status, _, _, body = _get(WebEditor(str(tmp_path)), "/")
    links = _Links()
    links.feed(body.decode("utf-8"))
    assert status == 200
    assert "/api/export-all" in links.downloads
