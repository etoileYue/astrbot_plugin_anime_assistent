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
        qq_id = event.get_sender_id()
        user = await self._db.ensure_user(qq_id)
        umo = event.unified_msg_origin

        engine = InterviewEngine(
            self._plugin, self._db, self._config,
            subject_id=subject_id, episode=episode,
            subject_name=subject_name, subject_name_cn=subject_name_cn,
            user_id=user.id,
        )
        question = await engine.start(umo)
        if question is None:
            return None

        self._active_sessions[(user.id, subject_id, episode)] = engine
        return question

    async def handle_message(self, event) -> str | None:
        """检查消息是否属于活跃访谈，如果是则处理回复。"""
        qq_id = event.get_sender_id()
        user = await self._db.get_user(qq_id)
        if user is None:
            return None

        for (uid, sid, ep), engine in list(self._active_sessions.items()):
            if uid == user.id:
                response = await engine.handle_answer(event.message_str, event.unified_msg_origin)
                if engine.state == InterviewState.ENDED:
                    await self._save_markdown(engine, uid)
                    del self._active_sessions[(uid, sid, ep)]
                return response

        return None

    async def _save_markdown(self, engine: InterviewEngine, user_id: int):
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

    def has_active_session(self, user_id: int) -> bool:
        return any(uid == user_id for uid, _, _ in self._active_sessions)
