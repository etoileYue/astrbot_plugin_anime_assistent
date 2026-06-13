"""scraper/bangumi.py 单元测试。"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.bangumi import BangumiScraper, Comment

# ---------------------------------------------------------------------------
# HTML 测试夹具
# ---------------------------------------------------------------------------


def _wrap_in_comment_list(*comments_html: str) -> str:
    """将评论 HTML 包裹在 #comment_list 容器中。"""
    joined = "\n".join(comments_html)
    return f"""<html><body>
<div id="comment_list">
{joined}
</div>
</body></html>"""


def _make_comment_html(post_id: int, username: str, floor: int, date: str, text: str) -> str:
    return f"""<div id="post_{post_id}" class="row_reply clearit" data-item-user="{username}">
  <div class="post_actions re_info">
    <div class="action">
      <small><a href="#post_{post_id}" class="floor-anchor">#{floor}</a> - {date}</small>
    </div>
  </div>
  <a href="/user/{username}" class="avatar">...</a>
  <div class="inner">
    <strong><a href="/user/{username}" class="l post_author_{post_id}">{username}</a></strong>
    <div class="reply_content">
      <div class="message clearit">{text}</div>
    </div>
  </div>
</div>"""


# 三条完整评论构成的页面
FULL_PAGE_HTML = _wrap_in_comment_list(
    _make_comment_html(1, "user_a", 1, "2023-10-1 12:00", "这集作画真棒！"),
    _make_comment_html(2, "user_b", 2, "2023-10-1 12:30", "剧情转折有点突然"),
    _make_comment_html(3, "user_c", 3, "2023-10-1 13:00", "ED 插入的时机无敌了"),
)

# 无评论页面
EMPTY_PAGE_HTML = "<html><body><div id='comment_list'></div></body></html>"

# 无 #comment_list 容器
NO_COMMENT_LIST_HTML = "<html><body><p>no comments here</p></body></html>"


# ---------------------------------------------------------------------------
# Comment 数据类
# ---------------------------------------------------------------------------

class TestComment:
    def test_create(self):
        c = Comment(username="alice", text="好看", timestamp="2023-10-1 12:00", floor=1)
        assert c.username == "alice"
        assert c.text == "好看"
        assert c.timestamp == "2023-10-1 12:00"
        assert c.floor == 1

    def test_equality(self):
        a = Comment("u", "t", "ts", 1)
        b = Comment("u", "t", "ts", 1)
        assert a == b


# ---------------------------------------------------------------------------
# _parse_comments
# ---------------------------------------------------------------------------

class TestParseComments:
    def test_basic_parsing(self):
        scraper = BangumiScraper()
        comments = scraper._parse_comments(FULL_PAGE_HTML, limit=30)
        assert len(comments) == 3
        assert comments[0] == Comment("user_a", "这集作画真棒！", "2023-10-1 12:00", 1)
        assert comments[1] == Comment("user_b", "剧情转折有点突然", "2023-10-1 12:30", 2)
        assert comments[2] == Comment("user_c", "ED 插入的时机无敌了", "2023-10-1 13:00", 3)

    def test_respects_limit(self):
        scraper = BangumiScraper()
        comments = scraper._parse_comments(FULL_PAGE_HTML, limit=2)
        assert len(comments) == 2

    def test_empty_comment_list(self):
        scraper = BangumiScraper()
        comments = scraper._parse_comments(EMPTY_PAGE_HTML, limit=30)
        assert comments == []

    def test_no_comment_list_element(self):
        scraper = BangumiScraper()
        comments = scraper._parse_comments(NO_COMMENT_LIST_HTML, limit=30)
        assert comments == []

    def test_empty_html(self):
        scraper = BangumiScraper()
        comments = scraper._parse_comments("", limit=30)
        assert comments == []

    def test_missing_username_fallback(self):
        """strong a.l 缺失时用户名为 '未知用户'。"""
        html = _wrap_in_comment_list("""<div id="post_1" class="row_reply">
  <div class="inner">
    <div class="reply_content"><div class="message">test</div></div>
  </div>
</div>""")
        scraper = BangumiScraper()
        comments = scraper._parse_comments(html, limit=30)
        assert len(comments) == 1
        assert comments[0].username == "未知用户"
        assert comments[0].text == "test"

    def test_missing_floor_timestamp(self):
        """floor-anchor 缺失时 floor=0, timestamp=''。"""
        html = _wrap_in_comment_list("""<div id="post_1" class="row_reply">
  <div class="inner">
    <strong><a class="l">user</a></strong>
    <div class="reply_content"><div class="message">test</div></div>
  </div>
</div>""")
        scraper = BangumiScraper()
        comments = scraper._parse_comments(html, limit=30)
        assert len(comments) == 1
        assert comments[0].floor == 0
        assert comments[0].timestamp == ""

    def test_malformed_floor_parsed_as_zero(self):
        """#N 部分无法解析为整数时 floor=0。"""
        html = _wrap_in_comment_list("""<div id="post_1" class="row_reply">
  <div class="post_actions re_info"><div class="action">
    <small><a class="floor-anchor">#abc</a> - 2023-10-1 12:00</small>
  </div></div>
  <div class="inner">
    <strong><a class="l">user</a></strong>
    <div class="reply_content"><div class="message">test</div></div>
  </div>
</div>""")
        scraper = BangumiScraper()
        comments = scraper._parse_comments(html, limit=30)
        assert len(comments) == 1
        assert comments[0].floor == 0
        assert comments[0].timestamp == "2023-10-1 12:00"

    def test_missing_message_text(self):
        """div.message 缺失时 text=''。"""
        html = _wrap_in_comment_list("""<div id="post_1" class="row_reply">
  <div class="post_actions re_info"><div class="action">
    <small><a class="floor-anchor">#1</a> - 2023-10-1 12:00</small>
  </div></div>
  <div class="inner">
    <strong><a class="l">user</a></strong>
    <div class="reply_content"></div>
  </div>
</div>""")
        scraper = BangumiScraper()
        comments = scraper._parse_comments(html, limit=30)
        assert len(comments) == 1
        assert comments[0].text == ""


# ---------------------------------------------------------------------------
# get_episode_comments — 缓存
# ---------------------------------------------------------------------------

class TestGetEpisodeCommentsCache:
    @pytest.mark.asyncio
    async def test_cache_hit_no_request(self):
        """缓存命中时不发起 HTTP 请求。"""
        scraper = BangumiScraper()
        scraper._cache[42] = (time.time(), [
            Comment("cached_user", "cached text", "2023-10-1", 1),
        ])

        # 不 mock _get_client — 如果发了请求会因连接失败而报错
        comments = await scraper.get_episode_comments(42)
        assert len(comments) == 1
        assert comments[0].username == "cached_user"

    @pytest.mark.asyncio
    async def test_cache_hit_respects_limit(self):
        """缓存返回时也受 limit 限制。"""
        scraper = BangumiScraper()
        scraper._cache[42] = (time.time(), [
            Comment("u1", "t1", "ts", 1),
            Comment("u2", "t2", "ts", 2),
            Comment("u3", "t3", "ts", 3),
        ])
        comments = await scraper.get_episode_comments(42, limit=2)
        assert len(comments) == 2

    @pytest.mark.asyncio
    async def test_cache_expired_fetches_again(self):
        """TTL 过期后重新请求。"""
        scraper = BangumiScraper(cache_ttl=1)
        # 放入过期缓存
        scraper._cache[42] = (time.time() - 9999, [
            Comment("old", "stale", "", 0),
        ])

        mock_client = AsyncMock()
        mock_client.get.return_value.text = FULL_PAGE_HTML
        mock_client.get.return_value.raise_for_status = MagicMock()
        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(42)
        assert len(comments) == 3  # 来自新页面


# ---------------------------------------------------------------------------
# get_episode_comments — 成功请求
# ---------------------------------------------------------------------------

class TestGetEpisodeCommentsSuccess:
    @pytest.mark.asyncio
    async def test_fetch_and_cache(self):
        """首次请求成功后写入缓存。"""
        scraper = BangumiScraper()
        mock_client = AsyncMock()
        mock_client.get.return_value.text = FULL_PAGE_HTML
        mock_client.get.return_value.raise_for_status = MagicMock()

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(99, limit=20)

        assert len(comments) == 3
        assert comments[0].username == "user_a"
        # 验证写入缓存
        assert 99 in scraper._cache
        _, cached = scraper._cache[99]
        assert len(cached) == 3

    @pytest.mark.asyncio
    async def test_fetch_single_comment_page(self):
        """只有一条评论的页面。"""
        html = _wrap_in_comment_list(
            _make_comment_html(1, "solo", 1, "2023-10-1", "唯一评论")
        )
        scraper = BangumiScraper()
        mock_client = AsyncMock()
        mock_client.get.return_value.text = html
        mock_client.get.return_value.raise_for_status = MagicMock()

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(1)
        assert len(comments) == 1
        assert comments[0].username == "solo"


# ---------------------------------------------------------------------------
# get_episode_comments — 错误处理
# ---------------------------------------------------------------------------

class TestGetEpisodeCommentsErrors:
    @pytest.mark.asyncio
    async def test_http_404_returns_empty(self):
        """HTTP 4xx 错误返回空列表。"""
        import httpx

        scraper = BangumiScraper()
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found", request=MagicMock(), response=MagicMock(status_code=404)
        )
        mock_client.get.return_value = resp

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(999999)
        assert comments == []
        assert 999999 not in scraper._cache

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        """网络错误返回空列表。"""
        import httpx

        scraper = BangumiScraper()
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("connection refused")

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(42)
        assert comments == []
        assert 42 not in scraper._cache

    @pytest.mark.asyncio
    async def test_broken_html_returns_empty(self):
        """解析完全失败时返回空列表（不抛异常）。"""
        scraper = BangumiScraper()
        mock_client = AsyncMock()
        mock_client.get.return_value.text = "<html><blink>not valid</blink></html>"
        mock_client.get.return_value.raise_for_status = MagicMock()

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(42)
        assert comments == []


# ---------------------------------------------------------------------------
# get_episode_comments — 默认参数
# ---------------------------------------------------------------------------

class TestGetEpisodeCommentsDefaults:
    @pytest.mark.asyncio
    async def test_default_limit_is_30(self):
        """未传 limit 时使用实例的 comment_limit（默认 30）。"""
        scraper = BangumiScraper()
        mock_client = AsyncMock()
        mock_client.get.return_value.text = FULL_PAGE_HTML
        mock_client.get.return_value.raise_for_status = MagicMock()

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(99)
        # FULL_PAGE_HTML 只有 3 条，不足 30 条则全选
        assert len(comments) == 3

    @pytest.mark.asyncio
    async def test_custom_comment_limit(self):
        """实例化时设置 comment_limit，不传 limit 时使用该值。"""
        scraper = BangumiScraper(comment_limit=1)
        mock_client = AsyncMock()
        mock_client.get.return_value.text = FULL_PAGE_HTML
        mock_client.get.return_value.raise_for_status = MagicMock()

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(99)
        assert len(comments) == 1

    @pytest.mark.asyncio
    async def test_explicit_limit_overrides_default(self):
        """显式传入 limit 覆盖实例默认值。"""
        scraper = BangumiScraper(comment_limit=1)
        mock_client = AsyncMock()
        mock_client.get.return_value.text = FULL_PAGE_HTML
        mock_client.get.return_value.raise_for_status = MagicMock()

        with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
            comments = await scraper.get_episode_comments(99, limit=3)
        assert len(comments) == 3

    def test_use_cn_mirror_sets_base_url(self):
        """use_cn_mirror=True 时使用镜像域名。"""
        scraper = BangumiScraper(use_cn_mirror=True)
        # _get_client 是 lazy 的，通过 sync 方式检查 URL 选择逻辑
        # 直接验证配置被保存
        assert scraper._use_cn_mirror is True

    def test_default_no_cn_mirror(self):
        """默认不使用国内镜像。"""
        scraper = BangumiScraper()
        assert scraper._use_cn_mirror is False


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    @pytest.mark.asyncio
    async def test_close_without_client(self):
        scraper = BangumiScraper()
        await scraper.close()  # 不报错

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        scraper = BangumiScraper()
        mock_client = AsyncMock()
        scraper._client = mock_client
        await scraper.close()
        mock_client.aclose.assert_awaited_once()
        assert scraper._client is None
