"""访谈处理器 — 管理访谈会话和消息路由。"""

import asyncio
import logging
import re
from dataclasses import dataclass

from ..core.interview_engine import InterviewEngine, InterviewState
from ..storage.database import Database
from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)

ROUTING_RE = re.compile(
    r'^\[(.+?)\]\s*(\d{1,4})(?:\s*(?:-|~|至)\s*(\d{1,4}))?\s*[：:]\s*(.+)',
    re.DOTALL,
)


@dataclass
class RoutingInfo:
    identifier: str
    start_episode: int
    end_episode: int
    answer: str


@dataclass
class ManualStartResult:
    question: str | None = None
    subject_id: int = 0
    subject_name: str = ""
    subject_name_cn: str = ""
    error: str | None = None
    status: str = "failed"
    start_episode: int = 0
    end_episode: int = 0


@dataclass
class InterviewStartResult:
    """一次访谈启动请求的结果。"""

    status: str
    subject_id: int
    start_episode: int
    end_episode: int
    question: str | None = None


class InterviewHandler:
    def __init__(self, plugin, db: Database, config):
        self._plugin = plugin
        self._db = db
        self._config = config
        self._scraper = None  # 延迟初始化，避免未安装 bs4 时崩溃
        # 每部番剧只允许一个活跃会话；章节范围由引擎自身维护。
        self._active_sessions: dict[int, InterviewEngine] = {}
        self._session_locks: dict[int, asyncio.Lock] = {}

    async def try_start(self, event, subject_id: int, episode: int,
                        subject_name: str, subject_name_cn: str = "",
                        start_episode: int | None = None) -> InterviewStartResult:
        """进度同步后尝试发起或扩展访谈。"""
        return await self.try_start_auto(
            umo=event.unified_msg_origin,
            subject_id=subject_id,
            episode=episode,
            subject_name=subject_name,
            subject_name_cn=subject_name_cn,
            start_episode=start_episode,
        )

    async def try_start_auto(self, umo: str, subject_id: int, episode: int,
                             subject_name: str, subject_name_cn: str = "",
                             start_episode: int | None = None) -> InterviewStartResult:
        """自动触发访谈（无需 event 对象）。同番剧会话自动向最新进度扩展。"""
        start_episode = start_episode or episode
        lock = self._session_locks.setdefault(subject_id, asyncio.Lock())
        async with lock:
            existing = self._active_sessions.get(subject_id)
            if existing is not None:
                old_end_episode = existing.episode
                if episode <= old_end_episode:
                    return InterviewStartResult(
                        status="unchanged",
                        subject_id=subject_id,
                        start_episode=existing.start_episode,
                        end_episode=existing.episode,
                    )

                question = await existing.extend_to(episode, umo)
                return InterviewStartResult(
                    status="extended_pending" if question else "extended_active",
                    subject_id=subject_id,
                    start_episode=existing.start_episode,
                    end_episode=existing.episode,
                    question=question,
                )

            if self._scraper is None:
                try:
                    from ..scraper.bangumi import BangumiScraper
                    self._scraper = BangumiScraper(
                        comment_limit=self._config.scraper_comment_limit,
                        use_cn_mirror=self._config.use_cn_mirror,
                        proxy=self._config.bangumi_proxy or None,
                    )
                except ImportError:
                    logger.warning("beautifulsoup4 未安装，评论爬取不可用")

            engine = InterviewEngine(
                self._plugin, self._db, self._config,
                subject_id=subject_id, episode=episode,
                subject_name=subject_name, subject_name_cn=subject_name_cn,
                scraper=self._scraper,
                start_episode=start_episode,
            )
            question = await engine.start(umo)
            if question is None:
                return InterviewStartResult(
                    status="failed", subject_id=subject_id,
                    start_episode=start_episode, end_episode=episode,
                )

            self._active_sessions[subject_id] = engine
            return InterviewStartResult(
                status="started", subject_id=subject_id,
                start_episode=engine.start_episode, end_episode=engine.episode,
                question=question,
            )

    async def start_manual(self, umo: str, identifier: str, episode: int) -> ManualStartResult:
        """手动触发访谈：解析标识符、获取番剧信息、开始访谈。

        标识符可以是 subject_id（数字）或追番别名。
        """
        # 解析标识符
        subject_id = await self._resolve_identifier(identifier)
        if subject_id is None:
            return ManualStartResult(
                error=f"未找到「{identifier}」的追番记录。\n"
                       f"请先使用 /sub add 添加追番，或使用 subject_id。"
            )

        # 获取番剧信息
        sub = await self._db.get_subscription(subject_id)
        if sub:
            subject_name = sub.subject_name
            subject_name_cn = sub.subject_name_cn or ""
        else:
            from ..api.bangumi import BangumiClient
            client = BangumiClient(self._config)
            try:
                subject = await client.get_subject(subject_id)
                subject_name = subject.name
                subject_name_cn = subject.name_cn
            except Exception as e:
                return ManualStartResult(error=f"获取番剧信息失败：{e}")
            finally:
                await client.close()

        # 发起访谈
        start_result = await self.try_start_auto(
            umo=umo,
            subject_id=subject_id,
            episode=episode,
            subject_name=subject_name,
            subject_name_cn=subject_name_cn,
        )

        if start_result.status == "failed":
            name = subject_name_cn or subject_name
            return ManualStartResult(
                error=f"无法为《{name}》第{episode}集生成访谈问题，请检查 LLM 配置。"
            )

        return ManualStartResult(
            question=start_result.question,
            subject_id=subject_id,
            subject_name=subject_name,
            subject_name_cn=subject_name_cn,
            status=start_result.status,
            start_episode=start_result.start_episode,
            end_episode=start_result.end_episode,
        )

    async def handle_message(self, event) -> str | None:
        """检查消息是否属于活跃访谈，如果是则处理回复。

        单会话：直接路由。
        多会话：解析 [番剧标识] 集数或范围：回复 格式的路由前缀。
        """
        text = event.message_str.strip()
        sessions = list(self._active_sessions.items())

        if len(sessions) == 1:
            subject_id, engine = sessions[0]
            return await self._route_to(subject_id, engine, text, event.unified_msg_origin)

        routing = self._parse_routing(text)
        if routing is None or not routing.answer:
            return self._routing_help_prompt()

        subject_id = await self._resolve_identifier(routing.identifier)
        if subject_id is None:
            return f"没有找到「{routing.identifier}」的追番记录，请检查名称或使用 subject_id。"

        engine = self._active_sessions.get(subject_id)
        if engine is None:
            return f"没有找到 subject_id={subject_id} 的活跃访谈。"

        if (routing.start_episode, routing.end_episode) != (
            engine.start_episode, engine.episode
        ):
            return (
                f"《{engine.subject_name}》"
                f"{self._format_episode_range(routing.start_episode, routing.end_episode)}"
                "没有活跃的访谈。\n"
                f"当前活跃的是{self._format_episode_range(engine.start_episode, engine.episode)}。"
            )
        return await self._route_to(subject_id, engine, routing.answer, event.unified_msg_origin)

    async def _route_to(self, subject_id: int, engine: InterviewEngine,
                        answer: str, umo: str) -> str | None:
        lock = self._session_locks.setdefault(subject_id, asyncio.Lock())
        async with lock:
            if self._active_sessions.get(subject_id) is not engine:
                return None
            response = await engine.handle_answer(answer, umo)
            if response is not None and engine.state == InterviewState.ENDED:
                await self._save_markdown(engine)
                self._active_sessions.pop(subject_id, None)
            return response

    def _parse_routing(self, text: str) -> RoutingInfo | None:
        """解析 [番剧名或ID] 集数或范围：回复内容 格式。"""
        m = ROUTING_RE.match(text)
        if not m:
            return None
        return RoutingInfo(
            identifier=m.group(1).strip(),
            start_episode=int(m.group(2)),
            end_episode=int(m.group(3) or m.group(2)),
            answer=m.group(4).strip(),
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
        for sid, engine in self._active_sessions.items():
            name = engine.subject_name
            lines.append(
                f"  [{sid}] {self._format_episode_range(engine.start_episode, engine.episode)} — {name}"
            )
        lines.append("")
        lines.append("格式：[番剧名或ID] 集数或范围：回复内容")
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
            episode_start=engine.start_episode,
            qa_pairs=qa_pairs,
            subject_id=engine.subject_id,
        )
        logger.info(f"访谈记录已保存: {filepath}")

    def get_routing_hint(self, exclude_subject_id: int | None = None) -> str:
        """如果存在多个活跃会话，返回路由前缀提示；否则返回空字符串。

        exclude_subject_id: 可选，排除某个番剧，用于只提示"其他"会话。
        """
        sessions = [
            (sid, engine)
            for sid, engine in self._active_sessions.items()
            if sid != exclude_subject_id
        ]
        if not sessions:
            return ""
        lines = [
            "",
            "📋 回复时请加上路由前缀，指定要回复的访谈：",
            "",
        ]
        for sid, engine in sessions:
            lines.append(
                f"  [{sid}] {self._format_episode_range(engine.start_episode, engine.episode)} — {engine.subject_name}"
            )
        lines.append("")
        lines.append("格式：[番剧名或ID] 集数或范围：回复内容")
        lines.append("例如：[上伊那牡丹] 9：我觉得这集...")
        return "\n".join(lines)

    def has_active_session(self, subject_id: int = 0, start_episode: int = 0,
                           end_episode: int = 0) -> bool:
        if subject_id and start_episode and end_episode:
            engine = self._active_sessions.get(subject_id)
            return bool(engine and (engine.start_episode, engine.episode) == (
                start_episode, end_episode
            ))
        if subject_id:
            return subject_id in self._active_sessions
        return len(self._active_sessions) > 0

    @staticmethod
    def _format_episode_range(start_episode: int, end_episode: int) -> str:
        if start_episode == end_episode:
            return f"第{end_episode}集"
        return f"第{start_episode}-{end_episode}集"
