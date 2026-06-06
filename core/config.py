from astrbot.api import AstrBotConfig


class PluginConfig:
    """插件配置封装，从 AstrBot 配置系统中读取。"""

    def __init__(self, config: AstrBotConfig):
        self._config = config

    @property
    def bangumi_client_id(self) -> str:
        return self._config.get("bangumi_client_id", "")

    @property
    def bangumi_client_secret(self) -> str:
        return self._config.get("bangumi_client_secret", "")

    @property
    def check_interval_hours(self) -> float:
        return self._config.get("check_interval_hours", 2.0)

    @property
    def max_interview_rounds(self) -> int:
        return self._config.get("max_interview_rounds", 3)

    @property
    def anime_notes_dir(self) -> str:
        return self._config.get("anime_notes_dir", "anime_notes")

    def save(self):
        self._config.save_config()
