import asyncio
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core.config import PluginConfig
from .core.scheduler import UpdateScheduler
from .handlers.interview import InterviewHandler
from .handlers.progress import ProgressHandler
from .handlers.subscription import SubscriptionHandler
from .storage.database import Database


@register(
    "bangumibot",
    "etoile_yue",
    "追番管理插件 — 搜索番剧、同步观看进度、LLM 观感访谈、自动生成 Markdown 记录",
    "0.1.0",
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.plugin_config = PluginConfig(config)
        self.db = Database()
        self.interview_handler = InterviewHandler(self, self.db, self.plugin_config)
        self.scheduler = UpdateScheduler(self, interview_handler=self.interview_handler)
        self._pending_confirms: dict[str, dict] = {}

    async def initialize(self):
        self._data_path = str(Path(get_astrbot_data_path()) / "plugin_data" / self.name)
        await self.db.initialize(self._data_path)

        # 从 Bangumi 同步「在看」列表
        try:
            from .core.sync import sync_from_bangumi
            total, added, updated, removed, _ = await sync_from_bangumi(self.db, self.plugin_config)
            logger.info(f"Bangumi 同步：新增 {added}，更新 {updated}，删除 {removed}，共 {total} 部在看番剧")
        except Exception as e:
            logger.warning(f"Bangumi 同步失败（不影响插件启动）：{e}")

        asyncio.create_task(self.scheduler.run())

    def _get_notes_dir(self) -> str:
        """返回观感记录目录：优先用户自定义，否则在 data_path 下。"""
        custom = self.plugin_config.anime_notes_dir
        if custom:
            return custom
        return str(Path(self._data_path) / "anime_notes")

    def _ensure_umo(self, event: AstrMessageEvent):
        """注册 UMO 以便调度器推送通知。"""
        self.scheduler.set_umo(event.unified_msg_origin)

    # === 帮助 ===

    @filter.command("bangumi")
    async def cmd_bangumi(self, event: AstrMessageEvent):
        """显示所有可用命令。用法：/bangumi"""
        lines = [
            "BangumiBot 可用命令：",
            "",
            "  /search <关键词>    搜索 Bangumi 番剧",
            "  /sub add <番剧名称>  添加追番",
            "  /sub list            查看追番列表",
            "  /sub remove <subject_id>  移除追番",
            "  /sync                同步 Bangumi 数据并检查番剧更新",
            "  /notes list          查看观感记录",
            "  /bangumi             显示本帮助",
        ]
        yield event.plain_result("\n".join(lines))

    # === 搜索 ===

    @filter.command("search")
    async def cmd_search(self, event: AstrMessageEvent, *, keyword: str = ""):
        """搜索 Bangumi 番剧。用法：/search <关键词>"""
        self._ensure_umo(event)
        if not keyword:
            yield event.plain_result("用法：/search <关键词>\n例如：/search 芙莉莲")
            return
        from .api.bangumi import BangumiClient

        client = BangumiClient(self.plugin_config)
        try:
            results = await client.search_subject(keyword)
        finally:
            await client.close()
        if not results:
            yield event.plain_result(f"未找到与「{keyword}」相关的结果。")
            return
        lines = [f"搜索「{keyword}」的结果："]
        for i, sub in enumerate(results[:5]):
            name = sub.name_cn or sub.name
            eps = f"{sub.eps}集" if sub.eps else "集数未知"
            lines.append(f"{i+1}. [{sub.id}] {name} ({eps})")
        yield event.plain_result("\n".join(lines))

    # === 追番管理 ===

    @filter.command_group("sub")
    def sub_group(self):
        """追番列表管理"""
        pass

    @sub_group.command("add")
    async def cmd_sub_add(self, event: AstrMessageEvent, *, name: str = ""):
        """添加追番。用法：/sub add <番剧名称>"""
        self._ensure_umo(event)
        if not name:
            yield event.plain_result("用法：/sub add <番剧名称>\n例如：/sub add 葬送的芙莉莲")
            return

        handler = SubscriptionHandler(self.db, self.plugin_config)
        result = await handler.add_by_name(name)

        if isinstance(result, str):
            yield event.plain_result(result)
            return

        # 无精确匹配，调用 LLM 选择
        search_text = result["search_text"]
        options: list = result["options"]

        from .llm.client import LLMClient

        llm = LLMClient(self)
        prompt = (
            f"用户想添加追番，输入的名称是「{name}」。Bangumi搜索返回了以下结果：\n\n"
            f"{search_text}\n\n"
            f"请判断用户最可能指的是哪一部番剧，只回复数字序号（1-{len(options)}）。"
            f"如果都不像，回复 0。"
        )
        try:
            llm_resp = await llm.generate(prompt=prompt, umo=event.unified_msg_origin)
            choice = int(llm_resp.strip())
        except (ValueError, TypeError):
            choice = 0

        if 1 <= choice <= len(options):
            subject = options[choice - 1]
            display_name = subject.name_cn or subject.name
            self._pending_confirms[event.unified_msg_origin] = {
                "subject": subject,
                "user_input": name,
            }
            yield event.plain_result(
                f"你要添加的是「{display_name} [{subject.id}]」（{subject.eps}集）吗？\n"
                f"回复「是」确认添加，回复「否」取消。"
            )
        else:
            # LLM 无法确定，列出所有结果
            lines = [f"未找到与「{name}」完全匹配的番剧，搜索结果如下：", ""]
            lines.append(search_text)
            lines.append("")
            lines.append("请使用 /sub add <subject_id> 添加对应的番剧。")
            yield event.plain_result("\n".join(lines))

    @sub_group.command("list")
    async def cmd_sub_list(self, event: AstrMessageEvent):
        """查看追番列表。用法：/sub list"""
        self._ensure_umo(event)
        handler = SubscriptionHandler(self.db, self.plugin_config)
        result = await handler.list_subscriptions()
        yield event.plain_result(result)

    @sub_group.command("remove")
    async def cmd_sub_remove(self, event: AstrMessageEvent, subject_id: int):
        """移除追番。用法：/sub remove <subject_id>"""
        self._ensure_umo(event)
        handler = SubscriptionHandler(self.db, self.plugin_config)
        result = await handler.remove_subscription(subject_id)
        yield event.plain_result(result)

    # === 手动同步 ===

    @filter.command("sync")
    async def cmd_sync(self, event: AstrMessageEvent):
        """从 Bangumi 同步数据并检查番剧更新。"""
        self._ensure_umo(event)
        await self.scheduler.check_once()
        yield event.plain_result("已同步 Bangumi 数据并完成更新检查。")

    # === 观感记录 ===

    @filter.command_group("notes")
    def notes_group(self):
        """观感记录管理"""
        pass

    @notes_group.command("list")
    async def cmd_notes_list(self, event: AstrMessageEvent):
        """查看已有观感记录。用法：/notes list"""
        from .storage.markdown import MarkdownStorage

        storage = MarkdownStorage(self._get_notes_dir())
        seasons = storage.list_seasons()
        if not seasons:
            yield event.plain_result("暂无观感记录。")
            return
        lines = ["观感记录："]
        for season in sorted(seasons, reverse=True):
            animes = storage.list_animes(season)
            for anime in animes:
                lines.append(f"  [{season}] {anime}")
        yield event.plain_result("\n".join(lines))

    # === 消息路由（非命令消息） ===
    # 优先级：待确认 > 访谈会话 > 进度同步

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理非命令消息：待确认 → 访谈会话 → 进度同步。"""
        self._ensure_umo(event)

        # 0. 检查是否有待用户确认的添加请求
        umo = event.unified_msg_origin
        if umo in self._pending_confirms:
            pending = self._pending_confirms[umo]
            text = event.message_str.strip()
            yes_words = {"是", "yes", "y", "确认", "确定", "嗯", "对", "好", "是的", "对的"}
            no_words = {"否", "no", "n", "取消", "不要", "不是", "不", "不了"}
            if text.lower() in yes_words:
                handler = SubscriptionHandler(self.db, self.plugin_config)
                result = await handler.confirm_add(pending["subject"], pending["user_input"])
                del self._pending_confirms[umo]
                yield event.plain_result(result)
            elif text.lower() in no_words:
                del self._pending_confirms[umo]
                yield event.plain_result("已取消添加。")
            else:
                subject = pending["subject"]
                display_name = subject.name_cn or subject.name
                yield event.plain_result(
                    f"请回复「是」确认添加或「否」取消。\n"
                    f"你要添加的是：{display_name} [{subject.id}]"
                )
            return

        # 1. 检查是否有活跃的访谈会话
        if self.interview_handler.has_active_session():
            result = await self.interview_handler.handle_message(event)
            if result:
                yield event.plain_result(result)
            return

        # 2. 尝试进度同步
        progress_handler = ProgressHandler(self.db, self.plugin_config)
        sync_result = await progress_handler.try_sync(event)
        if sync_result:
            yield event.plain_result(sync_result.message)
            # 进度同步成功后，尝试发起访谈
            if sync_result.subject_id and sync_result.episode:
                question = await self.interview_handler.try_start(
                    event,
                    subject_id=sync_result.subject_id,
                    episode=sync_result.episode,
                    subject_name=sync_result.subject_name,
                    subject_name_cn=sync_result.subject_name_cn,
                )
                if question:
                    yield event.plain_result(
                        f'想聊聊这一集吗？\n\n{question}\n\n（随时可以说"不聊了"结束访谈）'
                    )

    async def terminate(self):
        await self.scheduler.stop()
        await self.db.close()
