from astrbot.api import AstrBotConfig


class PluginConfig:
    """插件配置封装，从 AstrBot 配置系统中读取。"""

    def __init__(self, config: AstrBotConfig):
        self._config = config

    @property
    def bangumi_access_token(self) -> str:
        return self._config.get("bangumi_access_token", "")

    @property
    def bangumi_mirror_url(self) -> str:
        """用户自定义的 Bangumi 镜像站点地址，留空表示使用官方站点。"""
        return str(self._config.get("bangumi_mirror_url", "") or "").strip()

    @property
    def check_interval_hours(self) -> float:
        return self._config.get("check_interval_hours", 2.0)

    @property
    def max_interview_rounds(self) -> int:
        return self._config.get("max_interview_rounds", 3)

    @property
    def scraper_comment_limit(self) -> int:
        """爬虫每条剧集拉取的评论数上限（默认 30）。"""
        return self._config.get("scraper_comment_limit", 30)

    @property
    def web_viewer_port(self) -> int:
        """Web 笔记查看器端口，0 禁用。"""
        return self._config.get("web_viewer_port", 58080)

    @property
    def web_editor_port(self) -> int:
        """Web 笔记编辑器端口，0 禁用。"""
        return self._config.get("web_editor_port", 58081)

    def save(self):
        self._config.save_config()
