"""访谈处理器 — 管理访谈会话和消息路由。"""

import logging
import re
from dataclasses import dataclass

from ..core.interview_engine import InterviewEngine, InterviewState
from ..storage.database import Database
from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)

ROUTING_RE = re.compile(r'^\[(.+?)\]\s*(\d{1,4})\s*[：:]\s*(.+)', re.DOTALL)


@dataclass
class RoutingInfo:
    identifier: str
    episode: int
    answer: str


class InterviewHandler:
    def __init__(self, plugin, db: Database, config):
        self._plugin = plugin
        self._db = db
        self._config = config
        self._scraper = None  # 延迟初始化，避免未安装 bs4 时崩溃
        self._active_sessions: dict[tuple, InterviewEngine] = {}

    async def try_start(self, event, subject_id: int, episode: int,
                        subject_name: str, subject_name_cn: str = "") -> str | None:
        """进度同步后尝试发起访谈。返回初始问题或 None。"""
        return await self.try_start_auto(
            umo=event.unified_msg_origin,
            subject_id=subject_id,
            episode=episode,
            subject_name=subject_name,
            subject_name_cn=subject_name_cn,
        )

    async def try_start_auto(self, umo: str, subject_id: int, episode: int,
                             subject_name: str, subject_name_cn: str = "") -> str | None:
        """自动触发访谈（无需 event 对象）。返回初始问题或 None。"""
        if self._scraper is None:
            try:
                from ..scraper.bangumi import BangumiScraper
                self._scraper = BangumiScraper(
                    comment_limit=self._config.scraper_comment_limit,
                    use_cn_mirror=self._config.use_cn_mirror,
                )
            except ImportError:
                logger.warning("beautifulsoup4 未安装，评论爬取不可用")

        engine = InterviewEngine(
            self._plugin, self._db, self._config,
            subject_id=subject_id, episode=episode,
            subject_name=subject_name, subject_name_cn=subject_name_cn,
            scraper=self._scraper,
        )
        question = await engine.start(umo)
        if question is None:
            return None

        self._active_sessions[(subject_id, episode)] = engine
        return question

    async def handle_message(self, event) -> str | None:
        """检查消息是否属于活跃访谈，如果是则处理回复。

        单会话：直接路由。
        多会话：解析 [番剧标识] 集数：回复 格式的路由前缀。
        """
        text = event.message_str.strip()
        sessions = list(self._active_sessions.items())

        if len(sessions) == 1:
            return await self._route_to(sessions[0], text, event.unified_msg_origin)

        routing = self._parse_routing(text)
        if routing is None or not routing.answer:
            return self._routing_help_prompt()

        subject_id = await self._resolve_identifier(routing.identifier)
        if subject_id is None:
            return f"没有找到「{routing.identifier}」的追番记录，请检查名称或使用 subject_id。"

        key = (subject_id, routing.episode)
        if key not in self._active_sessions:
            for (sid, ep), eng in self._active_sessions.items():
                if sid == subject_id:
                    return (
                        f"《{eng.subject_name}》第{routing.episode}集没有活跃的访谈。\n"
                        f"当前活跃的是第{ep}集。"
                    )
            return f"没有找到 subject_id={subject_id} 的活跃访谈。"

        for (sid, ep), engine in sessions:
            if (sid, ep) == key:
                return await self._route_to(((sid, ep), engine), routing.answer, event.unified_msg_origin)

    async def _route_to(self, session_item, answer: str, umo: str) -> str | None:
        (sid, ep), engine = session_item
        response = await engine.handle_answer(answer, umo)
        if response is not None:
            if engine.state == InterviewState.ENDED:
                await self._save_markdown(engine)
                del self._active_sessions[(sid, ep)]
            return response
        return None

    def _parse_routing(self, text: str) -> RoutingInfo | None:
        """解析 [番剧名或ID] 集数：回复内容 格式。"""
        m = ROUTING_RE.match(text)
        if not m:
            return None
        return RoutingInfo(
            identifier=m.group(1).strip(),
            episode=int(m.group(2)),
            answer=m.group(3).strip(),
        )

    async def _resolve_identifier(self, identifier: str) -> int | None:
        """将标识符解析为 subject_id。"""
        try:
            return int(identifier)
        except ValueError:
            pass
        alias_row = await self._db.find_by_alias(identifier)
        if alias_row:
            return alias_row.subject_id
        return None

    def _routing_help_prompt(self) -> str:
        lines = ["当前有多个活跃访谈，请使用以下格式指定要回复的番剧：", ""]
        for (sid, ep), engine in self._active_sessions.items():
            name = engine.subject_name
            lines.append(f"  [{sid}] 第{ep}集 — {name}")
        lines.append("")
        lines.append("格式：[番剧名或ID] 集数：回复内容")
        lines.append("例如：[上伊那牡丹] 9：我觉得这集...")
        return "\n".join(lines)

    async def _save_markdown(self, engine: InterviewEngine):
        qa_pairs = engine.get_qa_pairs()
        if not qa_pairs:
            return

        from ..api.bangumi import BangumiClient

        air_date = ""
        try:
            client = BangumiClient(self._config)
            subject = await client.get_subject(engine.subject_id)
            air_date = subject.air_date
            await client.close()
        except Exception:
            pass

        storage = MarkdownStorage(self._plugin._get_notes_dir())
        season = storage._get_season_dir(air_date)
        filepath = storage.save_episode(
            anime_name=engine.subject_name,
            season=season,
            episode=engine.episode,
            qa_pairs=qa_pairs,
            subject_id=engine.subject_id,
        )
        logger.info(f"访谈记录已保存: {filepath}")

    def get_routing_hint(self, exclude: tuple | None = None) -> str:
        """如果存在多个活跃会话，返回路由前缀提示；否则返回空字符串。

        exclude: 可选，排除某个 (subject_id, episode)，用于只提示"其他"会话。
        """
        sessions = [(k, e) for k, e in self._active_sessions.items() if k != exclude]
        if not sessions:
            return ""
        lines = [
            "",
            "📋 回复时请加上路由前缀，指定要回复的访谈：",
            "",
        ]
        for (sid, ep), engine in sessions:
            lines.append(f"  [{sid}] 第{ep}集 — {engine.subject_name}")
        lines.append("")
        lines.append("格式：[番剧名或ID] 集数：回复内容")
        lines.append("例如：[上伊那牡丹] 9：我觉得这集...")
        return "\n".join(lines)

    def has_active_session(self, subject_id: int = 0, episode: int = 0) -> bool:
        if subject_id and episode:
            return (subject_id, episode) in self._active_sessions
        return len(self._active_sessions) > 0
