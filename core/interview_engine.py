"""访谈引擎 — 管理多轮访谈对话的状态机。"""

import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)


class InterviewState(Enum):
    IDLE = auto()
    GENERATING = auto()
    WAITING = auto()
    FOLLOW_UP = auto()
    ENDED = auto()


INTERVIEW_SYSTEM_PROMPT = """你是一个友好的追番伙伴，正在和用户聊刚看完的动画。

你的任务是：
1. 根据番剧信息提出开放式问题，引导用户分享观感
2. 问题应具体、有深度，不要问"你觉得怎么样"这种笼统问题
3. 基于用户回答生成自然追问，像朋友聊天一样
4. 不要重复之前问过的问题
5. 如果用户表示不想继续聊（如"不聊了""先这样""结束"），回复一句简短的收尾

用中文交流，保持轻松自然的语气。回复直接是可发送的对话文本，不要加任何标签或前缀。"""


class InterviewEngine:
    """单次访谈的状态机。每个 (subject_id, episode) 创建一个实例。"""

    def __init__(self, plugin, db, config, subject_id: int, episode: int,
                 subject_name: str, subject_name_cn: str = "", scraper=None):
        self._plugin = plugin
        self._db = db
        self._config = config
        self._scraper = scraper
        self.subject_id = subject_id
        self.episode = episode
        self.subject_name = subject_name_cn or subject_name
        self.state = InterviewState.IDLE
        self.round = 0
        self.max_rounds = config.max_interview_rounds
        self._history: list[tuple[str, str]] = []  # [(question, answer), ...]
        self._comments_context: str = ""  # 缓存格式化后的评论，避免重复抓取

    async def start(self, umo: str) -> str | None:
        """生成初始问题并开始访谈。返回问题文本。"""
        self.state = InterviewState.GENERATING
        try:
            question = await self._generate_initial_question(umo)
            if not question:
                self.state = InterviewState.ENDED
                return None
            self.state = InterviewState.WAITING
            self.round = 1
            self._history.append((question, ""))
            # 保存到数据库
            await self._db.save_interview(
                subject_id=self.subject_id,
                episode=self.episode,
                question=question,
                round_num=self.round,
            )
            return question
        except Exception as e:
            logger.error(f"生成初始问题失败: {e}")
            self.state = InterviewState.ENDED
            return None

    async def handle_answer(self, answer: str, umo: str) -> str | None:
        """处理用户回答，返回追问或结束消息。"""
        if self.state != InterviewState.WAITING:
            return None

        # 检查用户是否想结束
        end_keywords = ["不聊了", "先这样", "结束", "拜拜", "再见", "就这样"]
        if any(kw in answer for kw in end_keywords):
            self.state = InterviewState.ENDED
            await self._save_final_answer(answer)
            return "好的，下次再聊~ 观感记录已保存。"

        # 更新当前轮的回答
        if self._history:
            self._history[-1] = (self._history[-1][0], answer)
        await self._db.save_interview(
            subject_id=self.subject_id,
            episode=self.episode,
            question=self._history[-1][0] if self._history else "",
            answer=answer,
            round_num=self.round,
        )

        # 判断是否达到最大轮数
        self.round += 1
        if self.round > self.max_rounds:
            self.state = InterviewState.ENDED
            closing = await self._generate_closing(umo)
            return closing or "聊得很开心！观感记录已保存。"

        # 生成追问
        self.state = InterviewState.FOLLOW_UP
        try:
            follow_up = await self._generate_follow_up(answer, umo)
            self.state = InterviewState.WAITING
            self._history.append((follow_up, ""))
            await self._db.save_interview(
                subject_id=self.subject_id,
                episode=self.episode,
                question=follow_up,
                round_num=self.round,
            )
            return follow_up
        except Exception as e:
            logger.error(f"生成追问失败: {e}")
            self.state = InterviewState.ENDED
            return "聊得很开心！观感记录已保存。"

    async def _get_comments_context(self) -> str:
        """获取剧集评论上下文，失败时返回空字符串。结果会缓存在实例中。"""
        if self._scraper is None:
            return ""
        if self._comments_context:
            return self._comments_context
        try:
            from ..api.bangumi import BangumiClient

            client = BangumiClient(self._config)
            try:
                episodes = await client.get_episodes(self.subject_id)
            finally:
                await client.close()

            episode_id = None
            for ep in episodes:
                if ep.ep == self.episode:
                    episode_id = ep.id
                    break
            if episode_id is None:
                return ""

            comments = await self._scraper.get_episode_comments(episode_id)
            if not comments:
                return ""

            lines = []
            for c in comments:
                lines.append(f"- {c.username}: {c.text}")
            self._comments_context = "\n".join(lines)
            return self._comments_context
        except Exception:
            logger.warning("获取评论上下文失败", exc_info=True)
            return ""

    async def _generate_initial_question(self, umo: str) -> str:
        await self._get_comments_context()  # 触发抓取并缓存到 self._comments_context
        prompt = f"用户刚看完《{self.subject_name}》第{self.episode}集。\n"
        if self._comments_context:
            prompt += (
                f"\n以下是其他观众对这一集的讨论：\n{self._comments_context}\n\n"
                f"请基于以上讨论点，提出一个开放式问题，引导用户分享对这一集的观感和想法。"
            )
        else:
            prompt += "请提出一个开放式问题，引导用户分享对这一集的观感和想法。"
        return await self._llm_chat(prompt, umo)

    async def _generate_follow_up(self, answer: str, umo: str) -> str:
        context = []
        for q, a in self._history:
            context.append({"role": "assistant", "content": q})
            if a:
                context.append({"role": "user", "content": a})
        context.append({"role": "user", "content": answer})

        if self._comments_context:
            prompt = (
                f"以下是一些观众对《{self.subject_name}》第{self.episode}集的讨论，"
                f"可作为追问话题参考：\n{self._comments_context}\n\n"
                f"基于上面的对话和以上参考讨论，提出一个自然的追问，深入探讨用户的观感。"
            )
        else:
            prompt = "基于上面的对话，提出一个自然的追问，深入探讨用户的观感。"

        return await self._llm_chat(prompt, umo, context)

    async def _generate_closing(self, umo: str) -> str:
        if self._comments_context:
            prompt = (
                f"用户刚聊完《{self.subject_name}》第{self.episode}集的观感。"
                f"以下是一些观众对这一集的讨论：\n{self._comments_context}\n\n"
                f"请说一句简短的收尾，可以呼应以上讨论中的观点，感谢用户的分享。"
            )
        else:
            prompt = (
                f"用户刚聊完《{self.subject_name}》第{self.episode}集的观感。"
                f"请说一句简短的收尾，感谢用户的分享。"
            )
        return await self._llm_chat(prompt, umo)

    async def _llm_chat(self, prompt: str, umo: str, context: list[dict] | None = None) -> str:
        from ..llm.client import LLMClient

        client = LLMClient(self._plugin)
        return await client.chat(
            prompt=prompt,
            system_prompt=INTERVIEW_SYSTEM_PROMPT,
            context=context,
            umo=umo,
        )

    async def _save_final_answer(self, answer: str):
        # 用户主动结束访谈时，移除最后一个未回答的问题，避免结束语被当作正式回答写入记录
        if self._history and not self._history[-1][1]:
            self._history.pop()

    def get_qa_pairs(self) -> list[tuple[str, str]]:
        """返回完整的问答对列表，用于 Markdown 保存。"""
        return [(q, a) for q, a in self._history if a]
