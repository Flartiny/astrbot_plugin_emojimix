import asyncio
import aiohttp
from typing import Optional, List, Dict, Any
import emoji # 导入 emoji 库
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp # 导入消息组件

@register("emojiMix", "Flartiny ", "合成emoji插件", "1.0.0")
class EmojiKitchenPlugin(Star):
    # --- 配置项 (保持不变) ---
    DEFAULT_DATE_CODES = ["20240315", "20231115", "20230405", "20221115", "20220110", "20210831", "20201001"]
    DEFAULT_BASE_URL_TEMPLATE = "https://www.gstatic.com/android/keyboard/emojikitchen/{date_code}/u{hex1}/u{hex1}_u{hex2}.png"
    DEFAULT_REQUEST_TIMEOUT = 3

    # --- 初始化 (保持不变) ---
    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        super().__init__(context)
        self.config = config if config else AstrBotConfig({})
        self.date_codes = self.config.get("date_codes", self.DEFAULT_DATE_CODES)
        self.base_url_template = self.config.get("base_url_template", self.DEFAULT_BASE_URL_TEMPLATE)
        self.request_timeout = self.config.get("request_timeout", self.DEFAULT_REQUEST_TIMEOUT)

    async def initialize(self):
        logger.info("EmojiKitchenPlugin 初始化完成。")
        pass

    async def terminate(self):
        logger.info("EmojiKitchenPlugin 正在终止。")
        pass

    # ---核心 Emoji 处理逻辑---
    def _get_emoji_hex_code(self, emoji_char: str) -> Optional[str]:
        """使用 emoji 库获取 Emoji 的十六进制代码"""
        try:
            # emoji.demojize 可以将 Emoji 转换为文本表示 (:smile:)，如果不是 Emoji 则原样返回
            # 我们需要的是原始字符的十六进制表示
            # 遍历 Emoji 字符的 code points
            hex_codes = []
            for char in emoji_char:
                # 如果是 Surrogate Pair
                if 0xD800 <= ord(char) <= 0xDBFF and len(emoji_char) > emoji_char.index(char) + 1 and 0xDC00 <= ord(emoji_char[emoji_char.index(char) + 1]) <= 0xDFFF:
                     # 计算完整的 code point
                    code_point = (((ord(char) - 0xD800) * 0x400) + (ord(emoji_char[emoji_char.index(char) + 1]) - 0xDC00) + 0x10000)
                    hex_codes.append(f'{code_point:x}')
                    # 跳过下一个字符，因为它已经是 surrogate pair 的一部分
                    emoji_char = emoji_char[emoji_char.index(char) + 1:]
                else:
                    hex_codes.append(f'{ord(char):x}')

            # 过滤掉 ZWJ (U+200D) 和 VS16 (U+FE0F)，因为它们通常不用于生成 URL 的基础 hex
            # 但在某些情况下，ZWJ 组成的序列需要完整的 hex codes，这里先简单过滤
            # 更准确的处理需要根据 Emoji Kitchen 的实际实现来看，但常见组合是去除 ZWJ
            filtered_hex_codes = [code for code in hex_codes if code not in ['200d', 'fe0f']]

            if not filtered_hex_codes:
                logger.warning(f"未能从 '{emoji_char}' 获取有效的过滤后十六进制代码。")
                return None

            # Emoji Kitchen URL 使用 '-' 分隔 code points
            return '-'.join(filtered_hex_codes)

        except Exception as e:
            logger.error(f"转换 Emoji '{emoji_char}' 到十六进制时出错: {e}")
            return None

    async def _find_emoji_kitchen_url_async(self, emoji1: str, emoji2: str) -> Optional[str]:
        hex1 = self._get_emoji_hex_code(emoji1)
        hex2 = self._get_emoji_hex_code(emoji2)

        if not hex1 or not hex2:
            logger.warning(f"无法为 '{emoji1}' 或 '{emoji2}' 获取有效的十六进制代码。")
            return None

        logger.info(f"正在尝试混合: {emoji1} (u{hex1}) + {emoji2} (u{hex2})")

        async with aiohttp.ClientSession() as session:
            urls_to_check = []
            for date_code in self.date_codes:
                try:
                    # Emoji Kitchen 通常要求 hex1 是 Unicode 顺序靠前的那个
                    if hex1 > hex2 and hex1 != hex2:
                        url1 = self.base_url_template.format(date_code=date_code, hex1=hex2, hex2=hex1)
                        urls_to_check.append(url1)
                    else:
                         url1 = self.base_url_template.format(date_code=date_code, hex1=hex1, hex2=hex2)
                         urls_to_check.append(url1)

                except KeyError as e:
                    logger.error(f"URL 模板格式错误或缺少键: {e}. 模板: '{self.base_url_template}'")
                    return None

            for url in urls_to_check:
                try:
                    async with session.head(url, timeout=self.request_timeout) as response:
                        if response.status == 200:
                            logger.info(f"找到有效的 Emoji Kitchen URL: {url}")
                            return url
                except asyncio.TimeoutError:
                    logger.warning(f"检查 URL 超时: {url}")
                except aiohttp.ClientError as e:
                    logger.warning(f"检查 URL 时发生网络错误 {url}: {e}")

        logger.info(f"未能找到 {emoji1} 和 {emoji2} 的有效混合 Emoji URL。")
        return None

    # --- 辅助函数：提取文本中的 Emoji ---
    def _extract_emojis_from_text(self, text: str) -> List[str]:
        """使用 emoji 库提取文本中所有独立的 Emoji 序列"""
        # emoji.emoji_list 返回一个列表，每个元素是一个字典，包含 'match_start', 'match_end', 'emoji'
        # 我们只需要 'emoji' 字段
        return [e['emoji'] for e in emoji.emoji_list(text)]

    # --- 内部处理合成并发送结果的方法 (保持不变) ---
    async def _process_and_send_mix(self, event: AstrMessageEvent, emoji1: str, emoji2: str):
        """内部方法，用于执行合成查找并发送结果"""
        logger.info(f"检测到混合请求: {emoji1} 和 {emoji2} (来自: {event.get_sender_name()})")
        try:
            result_url = await self._find_emoji_kitchen_url_async(emoji1, emoji2)
        except Exception as e:
            logger.error(f"执行 Emoji Kitchen URL 查找时发生意外错误: {e}", exc_info=True)
            result_url = None

        if result_url:
            logger.info(f"成功合成 {emoji1} + {emoji2}，发送图片: {result_url}")
            yield event.chain_result([Comp.Image.fromURL(result_url)])
        else:
            # 失败逻辑保持不变
            response_text = f"😟 抱歉，无法找到 {emoji1} 和 {emoji2} 的混合 Emoji。\n可能是这对组合不存在，或者输入的不是有效的单个 Emoji 哦。"
            logger.info(f"未能找到 {emoji1} + {emoji2} 的混合 Emoji。")
            yield event.plain_result(response_text)

    # --- 命令处理 (主要修改提取 Emoji 的部分) ---
    @filter.command("mixemoji", alias={"合成emoji", "emojimix"}, priority=1)
    async def mix_emoji_command(self, event: AstrMessageEvent):
        """(命令) 合成两个 Emoji。用法: /mixemoji <emoji1><emoji2> 或 /mixemoji <emoji1> <emoji2>"""
        input_text = event.message_str.strip()

        # 移除命令本身，以便只处理参数部分
        command_name_found = None
        for cmd in ["mixemoji", "合成emoji", "emojimix"]:
            if input_text.startswith(f"/{cmd}"):
                input_text = input_text[len(f"/{cmd}"):].strip()
                command_name_found = cmd
                break

        if not command_name_found:
             # 如果没有找到命令，可能是在处理别名或其他情况，这里直接使用原始 input_text
             # 但为了避免误触发，通常命令处理器会负责匹配命令本身。
             # 这里的逻辑是假定 filter.command 已经匹配到了命令前缀。
             # 我们可以保留原始逻辑，或者更严格地检查。这里保持与原逻辑类似，只移除命令部分。
             # 如果 event.message_str 确实包含了命令，上面的startswith会处理。
             pass


        # 添加日志，确认 input_text 的内容
        logger.debug(f"命令 /mixemoji 接收到的处理后参数文本: '{input_text}'")

        if not input_text:
            yield event.plain_result("🤔 请在命令后提供两个 Emoji 来合成。\n例如: `/mixemoji 😂👍`")
            # 确保停止事件，即使没有参数也由命令处理器处理了
            event.stop_event()
            return

        # 使用 emoji 库提取文本中的所有 Emoji
        emojis = self._extract_emojis_from_text(input_text)
        logger.debug(f"命令 /mixemoji 从 '{input_text}' 提取到 emojis: {emojis}")

        # 验证逻辑：确保恰好提取到两个 Emoji，并且原文除了这两个 Emoji 外没有其他非空白字符
        if len(emojis) == 2:
            # 构建一个只包含提取到的 Emoji 的字符串，并移除其中的空格
            extracted_emoji_str = "".join(emojis)
            # 从原始输入文本中移除提取到的 Emoji，看剩余部分是否只包含空白字符
            remaining_text = input_text
            for e in emojis:
                 # 为了准确替换，使用 replace 并限制替换次数为1
                remaining_text = remaining_text.replace(e, '', 1)

            if not remaining_text.strip(): # 如果剩余部分去除首尾空白后为空
                emoji1 = emojis[0]
                emoji2 = emojis[1]
                logger.info(f"命令 /mixemoji 解析成功: emoji1='{emoji1}', emoji2='{emoji2}'")
                async for result in self._process_and_send_mix(event, emoji1, emoji2):
                    yield result
            else:
                logger.warning(f"命令 /mixemoji 输入 '{input_text}' 包含除两个 Emoji 和空格外的其他字符: '{remaining_text.strip()}'")
                yield event.plain_result(f"🤔 请确保命令后只提供两个 Emoji (可以有空格分隔)。检测到额外字符: '{remaining_text.strip()}'")

        elif len(emojis) == 1:
            logger.warning(f"命令 /mixemoji 输入 '{input_text}' 只包含一个 Emoji。")
            yield event.plain_result("🤔 检测到只有一个 Emoji，请提供两个 Emoji 来合成。")
        elif len(emojis) > 2:
            logger.warning(f"命令 /mixemoji 输入 '{input_text}' 包含超过两个 Emoji。")
            yield event.plain_result("🤔 检测到超过两个 Emoji，请只提供两个 Emoji 来合成。")
        else:
            logger.warning(f"命令 /mixemoji 输入 '{input_text}' 未检测到有效的 Emoji。")
            yield event.plain_result("🤔 未能在输入中检测到有效的 Emoji，请提供两个 Emoji。")

        # 命令处理完成后阻止事件继续传播
        event.stop_event()

    # --- 新增：自动检测双 Emoji 消息 (主要修改提取 Emoji 的部分) ---
    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1) # 设置较低优先级
    async def handle_double_emoji_message(self, event: AstrMessageEvent):
        # 提取消息内容
        message_text = event.get_message_str().strip()
        if not message_text: # 忽略空消息
            return

        # 使用 emoji 库提取 Emoji
        emojis = self._extract_emojis_from_text(message_text)

        # 判断是否恰好是两个 Emoji，且原消息基本就是这两个 Emoji 组成
        if len(emojis) == 2:
            # 进一步检查，去除所有非 Emoji 字符后是否为空，或者只剩空格
            remaining_text = message_text
            for e in emojis:
                 # 为了准确替换，使用 replace 并限制替换次数为1
                remaining_text = remaining_text.replace(e, '', 1)


            if not remaining_text.strip(): # 如果移除 emojis 后只剩空格或为空
                emoji1 = emojis[0]
                emoji2 = emojis[1]

                logger.debug(f"自动检测到双 Emoji 消息: '{emoji1}' 和 '{emoji2}'")
                # 调用内部处理方法
                async for result in self._process_and_send_mix(event, emoji1, emoji2):
                    yield result
                # 处理完成后，停止事件传播，避免干扰 LLM 或其他插件
                event.stop_event()
            else:
                logger.debug(f"提取到两个 Emoji，但原消息包含其他字符: '{message_text}' -> '{remaining_text.strip()}'")