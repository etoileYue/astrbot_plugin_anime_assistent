from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core.config import PluginConfig
from .core.scheduler import UpdateScheduler
from .core.schedule import (
    WEEKDAY_INPUTS,
    WEEKDAY_NAMES,
    handled_marker_for_new_schedule,
    resolve_missing_schedules,
    resolve_schedule,
    valid_time,
)
from .core.web_viewer import WebViewer
from .core.web_editor import WebEditor
from .handlers.interview import InterviewHandler
from .handlers.progress import ProgressHandler
from .handlers.subscription import SubscriptionHandler
from .storage.database import Database


@register(
    "astrbot_plugin_bangumi_assistant",
    "etoileYue",
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
        self.web_viewer: WebViewer | None = None
        self.web_editor: WebEditor | None = None
        self._pending_confirms: dict[str, dict] = {}
        self._cmd_words = {"sync", "search", "sub", "notes", "bangumi"}

    async def initialize(self):
        self._data_path = str(Path(get_astrbot_data_path()) / "plugin_data" / self.name)
        await self.db.initialize(self._data_path)

        # Web 笔记查看器
        self.web_viewer = WebViewer(
            self._get_notes_dir(),
            port=self.plugin_config.web_viewer_port,
        )
        await self.web_viewer.start()

        # Web 笔记编辑器（独立端口，用于手动编辑 Markdown）
        self.web_editor = WebEditor(
            self._get_notes_dir(),
            port=self.plugin_config.web_editor_port,
        )
        await self.web_editor.start()

        # 从 Bangumi 同步「在看」列表
        try:
            from .core.sync import sync_from_bangumi
            total, added, updated, removed, _ = await sync_from_bangumi(self.db, self.plugin_config)
            logger.info(f"Bangumi 同步：新增 {added}，更新 {updated}，删除 {removed}，共 {total} 部在看番剧")
        except Exception as e:
            logger.warning(f"Bangumi 同步失败（不影响插件启动）：{e}")

        try:
            results = await resolve_missing_schedules(self.db, self.plugin_config)
            if results:
                logger.info(f"已完成 {len(results)} 条存量追番的排期查询")
        except Exception as e:
            logger.warning(f"存量排期查询失败（不影响插件启动）：{e}")

        self.scheduler.start()

    def _get_notes_dir(self) -> str:
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
            "  /sub schedule <番剧标识> <周一-周日> <HH:MM>  手动设置时间提醒",
            "  /sub schedule show <番剧标识>  查看排期",
            "  /sub schedule clear <番剧标识>  关闭更新提醒",
            "  /sub schedule auto <番剧标识>  重新从 MAL 获取排期",
            "  /sync                同步 Bangumi 数据并检查番剧更新",
            "  /note <标识> <集数>  手动触发观感访谈",
            "  /notes list          查看观感记录",
            "  /bangumi             显示本帮助",
            "",
            "Web 笔记查看器：http://<服务器IP>:58080（只读）",
            "Web 笔记编辑器：http://<服务器IP>:58081（编辑 Markdown）",
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

    async def _find_subscription(self, identifier: str):
        """用 subject_id 或已保存别名解析追番，供排期命令共享。"""
        identifier = identifier.strip()
        if identifier.isdigit():
            return await self.db.get_subscription(int(identifier))
        alias = await self.db.find_by_alias(identifier)
        return await self.db.get_subscription(alias.subject_id) if alias else None

    @sub_group.command("schedule")
    async def cmd_sub_schedule(
        self, event: AstrMessageEvent, operation_or_identifier: str = "",
        identifier_or_day: str = "", clock: str = "",
    ):
        """设置、查看或刷新北京时间更新排期。"""
        self._ensure_umo(event)
        usage = (
            "用法：\n"
            "/sub schedule <番剧标识> <周一-周日> <HH:MM>\n"
            "/sub schedule show|clear|auto <番剧标识>\n"
            "所有时间均为北京时间（UTC+8）。"
        )
        operation_or_identifier = operation_or_identifier.strip()
        identifier_or_day = identifier_or_day.strip()
        clock = clock.strip()
        if not operation_or_identifier:
            yield event.plain_result(usage)
            return

        # AstrBot 会按函数的显式位置参数绑定子命令参数；不要使用 *args/
        # 一个聚合字符串，否则在 command_group 下尾随文本可能不会被传入。
        action = operation_or_identifier
        if action in {"show", "clear", "auto"}:
            identifier = identifier_or_day
            if not identifier:
                yield event.plain_result(usage)
                return
            sub = await self._find_subscription(identifier)
            if not sub:
                yield event.plain_result(f"未找到「{identifier}」的追番记录。")
                return
            name = sub.subject_name_cn or sub.subject_name
            if action == "show":
                if not sub.airing and sub.schedule_weekday is not None and sub.schedule_time:
                    yield event.plain_result(f"《{name}》未启用更新提醒。")
                elif not sub.airing and sub.schedule_source != "manual":
                    yield event.plain_result(f"《{name}》未启用更新提醒。")
                elif sub.schedule_weekday is not None and sub.schedule_time:
                    source = "MAL 自动匹配" if sub.schedule_source == "mal" else "手动设置"
                    yield event.plain_result(
                        f"《{name}》的更新提醒：每周{WEEKDAY_NAMES[sub.schedule_weekday]} "
                        f"{sub.schedule_time}（{source}）。"
                    )
                elif sub.schedule_source == "manual":
                    yield event.plain_result(f"《{name}》的更新提醒已关闭。")
                else:
                    yield event.plain_result(f"《{name}》尚未设置有效排期；可手动设置或执行 /sub schedule auto {sub.subject_id}。")
                return
            if action == "clear":
                await self.db.set_schedule(
                    sub.subject_id, weekday=None, time=None, source="manual",
                    mal_id=sub.mal_id, last_notified_at=None, airing=0,
                )
                yield event.plain_result(f"已关闭《{name}》的自动更新提醒。")
                return

            result = await resolve_schedule(self.db, sub, self.plugin_config)
            if result.found:
                yield event.plain_result(f"《{name}》{result.message}。")
            else:
                yield event.plain_result(
                    f"《{name}》未能恢复自动排期：{result.message}。"
                    "可改用手动设置。"
                )
            return

        identifier, day = operation_or_identifier, identifier_or_day
        if not day or not clock:
            yield event.plain_result(usage)
            return
        if day not in WEEKDAY_INPUTS:
            yield event.plain_result("星期必须是周一、周二、周三、周四、周五、周六或周日。")
            return
        if not valid_time(clock):
            yield event.plain_result("时间必须是 24 小时制 HH:MM，例如 23:30。")
            return
        sub = await self._find_subscription(identifier)
        if not sub:
            yield event.plain_result(f"未找到「{identifier}」的追番记录。")
            return
        weekday = WEEKDAY_INPUTS[day]
        marker = handled_marker_for_new_schedule(weekday, clock)
        await self.db.set_schedule(
            sub.subject_id, weekday=weekday, time=clock, source="manual",
            mal_id=sub.mal_id, last_notified_at=marker, airing=1,
        )
        name = sub.subject_name_cn or sub.subject_name
        yield event.plain_result(
            f"已设置《{name}》：每周{day} {clock} 提醒（手动设置）。"
        )

    # === 手动同步 ===

    @filter.command("sync")
    async def cmd_sync(self, event: AstrMessageEvent):
        """从 Bangumi 同步数据并检查番剧更新。"""
        self._ensure_umo(event)
        results = await self.scheduler.check_once()
        if results:
            success = sum(result.found for result in results)
            yield event.plain_result(
                f"已同步 Bangumi 数据并完成更新检查；已刷新 {len(results)} 条自动排期，成功 {success} 条。"
            )
        else:
            yield event.plain_result("已同步 Bangumi 数据并完成更新检查；没有可刷新的自动排期。")

    # === 观感记录 ===

    @filter.command("note")
    async def cmd_note(self, event: AstrMessageEvent, *, args: str = ""):
        """手动触发访谈记录观感。用法：/note <番剧标识> <集数>"""
        self._ensure_umo(event)

        if not args.strip():
            yield event.plain_result(
                "用法：/note <番剧标识> <集数>\n"
                "番剧标识可以是 subject_id 或追番别名。\n"
                "例如：/note 芙莉莲 6"
            )
            return

        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请指定集数。用法：/note <番剧标识> <集数>")
            return

        try:
            episode = int(parts[1].strip())
        except ValueError:
            yield event.plain_result(f"集数必须是数字，收到：{parts[1]}")
            return
        if episode <= 0:
            yield event.plain_result("集数必须大于0。")
            return

        result = await self.interview_handler.start_manual(
            umo=event.unified_msg_origin,
            identifier=parts[0].strip(),
            episode=episode,
        )

        if result.error:
            yield event.plain_result(result.error)
            return

        name = result.subject_name_cn or result.subject_name
        msg = (
            f"来聊聊《{name}》第{episode}集吧！\n\n"
            f"{result.question}\n\n"
            f"（随时可以说\"不聊了\"结束访谈）"
        )
        hint = self.interview_handler.get_routing_hint(
            exclude=(result.subject_id, episode, episode)
        )
        if hint:
            msg += "\n" + hint
        yield event.plain_result(msg)

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

        # 跳过命令消息（AstrBot 可能将命令消息同时路由到 on_message，
        # 导致访谈引擎误将命令文本当作回答，污染对话上下文）
        text = event.message_str.strip()
        if text.startswith("/") or text in self._cmd_words:
            return

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
                    msg = f'想聊聊这一集吗？\n\n{question}\n\n（随时可以说"不聊了"结束访谈）'
                    hint = self.interview_handler.get_routing_hint(
                        exclude=(sync_result.subject_id, sync_result.episode, sync_result.episode)
                    )
                    if hint:
                        msg += "\n" + hint
                    yield event.plain_result(msg)

    async def terminate(self):
        # 每步清理独立 try/except：确保一处失败不阻断后续清理，
        # 尤其要保证 web server 的 socket 一定被释放，避免热重载时端口占用。
        try:
            await self.scheduler.stop()
        except Exception as e:
            logger.warning(f"停止调度器失败: {e}")
        if self.web_viewer:
            try:
                await self.web_viewer.stop()
            except Exception as e:
                logger.warning(f"停止 web_viewer 失败: {e}")
        if self.web_editor:
            try:
                await self.web_editor.stop()
            except Exception as e:
                logger.warning(f"停止 web_editor 失败: {e}")
        try:
            await self.db.close()
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")
