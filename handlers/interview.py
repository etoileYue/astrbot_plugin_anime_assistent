"""访谈处理器 — 管理访谈会话和消息路由。"""

import logging

from ..core.interview_engine import InterviewEngine, InterviewState
from ..storage.database import Database
from ..storage.markdown import MarkdownStorage

logger = logging.getLogger(__name__)


class InterviewHandler:
    def __init__(self, plugin, db: Database, config):
        self._plugin = plugin
        self._db = db
        self._config = config
        self._active_sessions: dict[tuple, InterviewEngine] = {}

    async def try_start(self, event, subject_id: int, episode: int,
                        subject_name: str, subject_name_cn: str = "") -> str | None:
        """进度同步后尝试发起访谈。返回初始问题或 None。"""
        umo = event.unified_msg_origin

        engine = InterviewEngine(
            self._plugin, self._db, self._config,
            subject_id=subject_id, episode=episode,
            subject_name=subject_name, subject_name_cn=subject_name_cn,
        )
        question = await engine.start(umo)
        if question is None:
            return None

        self._active_sessions[(subject_id, episode)] = engine
        return question

    async def handle_message(self, event) -> str | None:
        """检查消息是否属于活跃访谈，如果是则处理回复。"""
        for (sid, ep), engine in list(self._active_sessions.items()):
            response = await engine.handle_answer(event.message_str, event.unified_msg_origin)
            if engine.state == InterviewState.ENDED:
                await self._save_markdown(engine)
                del self._active_sessions[(sid, ep)]
            return response

        return None

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

    def has_active_session(self) -> bool:
        return len(self._active_sessions) > 0
