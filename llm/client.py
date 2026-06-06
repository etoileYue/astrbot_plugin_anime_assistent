"""LLM 客户端 — 封装 AstrBot 内置 LLM 调用。"""

import logging

logger = logging.getLogger(__name__)


class LLMClient:
    """统一的 LLM 调用接口，通过 AstrBot provider 系统调用。"""

    def __init__(self, plugin):
        self._plugin = plugin

    async def generate(self, prompt: str, system_prompt: str = "", umo: str = "") -> str:
        provider = self._plugin.context.get_using_provider(umo=umo)
        if not provider:
            logger.warning("No LLM provider configured")
            return ""
        resp = await provider.text_chat(
            prompt=prompt,
            system_prompt=system_prompt,
        )
        return resp.completion_text

    async def chat(
        self,
        prompt: str,
        system_prompt: str = "",
        context: list[dict] | None = None,
        umo: str = "",
    ) -> str:
        provider = self._plugin.context.get_using_provider(umo=umo)
        if not provider:
            logger.warning("No LLM provider configured")
            return ""
        resp = await provider.text_chat(
            prompt=prompt,
            system_prompt=system_prompt,
            context=context or [],
        )
        return resp.completion_text
