from typing import AsyncGenerator, Optional

import aiohttp
import astrbot.api.message_components as Comp
import emoji
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, register

def _remove_emojis_once(text: str, emojis: list[str]) -> str:
    cleaned_text = text
    for item in emojis:
        cleaned_text = cleaned_text.replace(item, "", 1)
    return cleaned_text


def _normalized_mix_key(emoji1: str, emoji2: str) -> tuple[str, str]:
    if emoji1 <= emoji2:
        return emoji1, emoji2
    return emoji2, emoji1


@register("emojiMix", "Flartiny ", "合成emoji插件", "")
class EmojiMixPlugin(Star):
    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        super().__init__(context)
        if config is None:
            raise ValueError("AstrBot 未注入插件配置对象。")

        self.date_codes: tuple[str, ...] = tuple(config.get("date_codes"))
        self.base_url_template: str = config.get("base_url_template")
        self.request_timeout: float = float(config.get("request_timeout"))
        self.auto_trigger: bool = config.get("auto_trigger")
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._result_cache: dict[tuple[str, str], str] = {}

    async def initialize(self):
        self._http_session = aiohttp.ClientSession()
        logger.info("EmojiMixPlugin 初始化完成。")

    async def terminate(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        logger.info("EmojiMixPlugin 正在终止。")

    def _extract_emojis_from_text(self, text: str) -> list[str]:
        return [item["emoji"] for item in emoji.emoji_list(text)]

    def _strip_command_prefix(self, text: str) -> str:
        cleaned_text = text.strip()
        prefixes = ["emojimix", "/emojimix"]
        for prefix in prefixes:
            if cleaned_text.startswith(prefix):
                cleaned_text = cleaned_text[len(prefix) :].strip()
                break
        return cleaned_text

    def _validate_command_input(
        self, input_text: str
    ) -> tuple[Optional[tuple[str, str]], Optional[str]]:
        if not input_text:
            return (
                None,
                "🤔 请在命令后提供两个 Emoji 来合成。\n例如: `/emojimix 💩😊`",
            )

        emojis = self._extract_emojis_from_text(input_text)
        emoji_count = len(emojis)
        if emoji_count == 1:
            return None, "🤔 检测到只有一个 Emoji，请提供两个 Emoji 来合成。"
        if emoji_count > 2:
            return None, "🤔 检测到超过两个 Emoji，请只提供两个 Emoji 来合成。"
        if emoji_count == 0:
            return None, "🤔 未能在输入中检测到有效的 Emoji，请提供两个 Emoji。"

        strict_result = self._extract_emojis_from_text(input_text)
        extra_text = _remove_emojis_once(input_text, strict_result).strip()
        if not extra_text:
            return (strict_result[0], strict_result[1]), None

        return (
            None,
            (
                "🤔 请确保命令后只提供两个 Emoji (可以有空格分隔)。"
                f"检测到额外字符: '{extra_text}'"
            ),
        )

    def _emoji_to_hex_code(self, emoji_text: str) -> str:
        return "-".join(f"u{ord(char):x}" for char in emoji_text)

    def _build_candidate_urls(self, hex1: str, hex2: str) -> tuple[str, ...]:
        urls: list[str] = []
        for date_code in self.date_codes:
            first_url = self.base_url_template.format(
                date_code=date_code,
                hex1=hex1,
                hex2=hex2,
            )
            urls.append(first_url)
            if hex1 != hex2:
                second_url = self.base_url_template.format(
                    date_code=date_code,
                    hex1=hex2,
                    hex2=hex1,
                )
                urls.append(second_url)
        return tuple(dict.fromkeys(urls))

    def _require_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            raise RuntimeError("HTTP 会话未初始化，请检查插件生命周期。")
        return self._http_session

    async def _is_url_available(self, url: str) -> bool:
        session = self._require_http_session()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        try:
            async with session.head(url, timeout=timeout) as response:
                return response.status == 200
        except TimeoutError:
            logger.warning(f"检查 URL 超时: {url}")
            return False
        except aiohttp.ClientError as exc:
            logger.warning(f"检查 URL 时发生网络错误 {url}: {exc}")
            return False

    async def _find_emoji_kitchen_url_async(
        self, emoji1: str, emoji2: str
    ) -> Optional[str]:
        cache_key = _normalized_mix_key(emoji1, emoji2)
        cached_url = self._result_cache.get(cache_key)
        if cached_url:
            logger.debug(f"命中缓存: {emoji1} + {emoji2} -> {cached_url}")
            return cached_url

        hex1 = self._emoji_to_hex_code(emoji1)
        hex2 = self._emoji_to_hex_code(emoji2)
        logger.info(f"正在尝试混合: {emoji1} ({hex1}) + {emoji2} ({hex2})")

        candidate_urls = self._build_candidate_urls(hex1, hex2)
        for url in candidate_urls:
            if await self._is_url_available(url):
                logger.info(f"找到有效的 Emoji Kitchen URL: {url}")
                self._result_cache[cache_key] = url
                return url

        logger.info(f"未能找到 {emoji1} 和 {emoji2} 的有效混合 Emoji URL。")
        return None

    async def _process_and_send_mix(
        self, event: AstrMessageEvent, emoji1: str, emoji2: str
    ) -> AsyncGenerator[MessageEventResult, None]:
        logger.info(
            f"检测到混合请求: {emoji1} 和 {emoji2} (来自: {event.get_sender_name()})"
        )

        result_url = await self._find_emoji_kitchen_url_async(emoji1, emoji2)
        if result_url:
            yield event.chain_result([Comp.Image.fromURL(result_url)])
            return

        response_text = (
            f"😟 抱歉，无法找到 {emoji1} 和 {emoji2} 的混合 Emoji。\n"
            "可能是这对组合不存在，或者输入的不是有效的单个 Emoji 哦。"
        )
        yield event.plain_result(response_text)

    @filter.command("emojimix")
    async def mix_emoji_command(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        """(命令) 合成两个 Emoji。用法: /emojimix <emoji1><emoji2>"""
        raw_text = event.message_str
        input_text = self._strip_command_prefix(raw_text)
        parse_result, error_message = self._validate_command_input(input_text)
        if error_message:
            yield event.plain_result(error_message)
            event.stop_event()
            return

        if parse_result is None:
            raise RuntimeError("输入解析状态异常：缺少有效的 emoji 结果。")

        emoji1, emoji2 = parse_result
        async for result in self._process_and_send_mix(event, emoji1, emoji2):
            yield result
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_double_emoji_message(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        """自动检测仅由两个 emoji 组成的消息并触发合成。"""
        if not self.auto_trigger:
            return

        message_text = event.get_message_str().strip()
        if not message_text or message_text.startswith("/"):
            return

        strict_result = self._extract_emojis_from_text(message_text)
        if len(strict_result) != 2:
            return

        text_without_emojis = _remove_emojis_once(message_text, strict_result)
        if text_without_emojis.strip():
            return

        emoji1, emoji2 = strict_result
        async for result in self._process_and_send_mix(event, emoji1, emoji2):
            yield result
        event.stop_event()
