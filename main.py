import asyncio
import aiohttp
from typing import Optional, List, Dict, Any
import re

# 从 AstrBot API 导入必要的模块
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp # 导入消息组件

# --- 正则表达式用于查找 Emoji ---
# 一个比较宽泛的模式，尝试匹配 Unicode Emoji 字符和序列
# 注意：这个模式可能不是完美的，复杂的 ZWJ 序列或新型 Emoji 可能匹配不准
EMOJI_PATTERN = re.compile(
    # 基本 Emoji, 符号, 图形符号, 交通和地图符号, 杂项符号和象形文字, 表情符号
    r'[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]'
    # 补充符号和象形文字
    r'|[\U0001FA70-\U0001FAFF]'
    # Dingbats
    r'|[\U00002700-\U000027BF]'
    # 杂项符号
    r'|[\U00002600-\U000026FF]'
    # 箭头, 数学运算符, 杂项技术符号, 控制图片, OCR, 盒子绘制, 块元素, 几何形状, 杂项符号, CJK 符号和标点, 私人使用区等可能包含类 Emoji 字符的区域 (选择性添加，可能误伤)
    # r'|[\U00002190-\U000021FF\U00002B00-\U00002BFF\U00002300-\U000023FF\U000025A0-\U000025FF\U00002B00-\U00002BFF]'
    # 允许连接符 (ZWJ) 和变体选择符 (VS16) 出现在序列中
    r'|[\u200d\ufe0f]'
    # 匹配一个或多个上述字符组成的序列
    r'+',
    re.UNICODE
)

# --- 插件注册信息 ---
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
        logger.debug(f"EmojiKitchen 使用的日期代码: {self.date_codes}")
        logger.debug(f"EmojiKitchen 使用的 URL 模板: {self.base_url_template}")
        logger.debug(f"EmojiKitchen 请求超时: {self.request_timeout}s")

    async def initialize(self):
        logger.info("EmojiKitchenPlugin 初始化完成。")
        pass

    async def terminate(self):
        logger.info("EmojiKitchenPlugin 正在终止。")
        pass

    # --- 核心 Emoji 处理逻辑 (内部辅助方法，保持不变) ---
    def _get_emoji_hex_code(self, emoji: str) -> Optional[str]:
        try:
            cleaned_emoji = emoji.replace('\ufe0f', '') # 移除 VS16
            if not cleaned_emoji: return None

            if '\u200d' in cleaned_emoji: # 处理 ZWJ 序列
                # 过滤掉 ZWJ 自身，并转换其他字符
                return '-'.join(f'{ord(c):x}' for c in cleaned_emoji if c != '\u200d')
            elif len(cleaned_emoji) >= 1: # 处理单个字符（包括代理对）
                first_char_code = ord(cleaned_emoji[0])
                if 0xD800 <= first_char_code <= 0xDBFF and len(cleaned_emoji) > 1 and 0xDC00 <= ord(cleaned_emoji[1]) <= 0xDFFF:
                    code_point = (((first_char_code - 0xD800) * 0x400) + (ord(cleaned_emoji[1]) - 0xDC00) + 0x10000)
                    return f'{code_point:x}'
                else:
                    return f'{first_char_code:x}'
            else:
                logger.warning(f"无法处理的 Emoji 格式: '{emoji}'")
                return None
        except Exception as e:
            logger.error(f"转换 Emoji '{emoji}' 到十六进制时出错: {e}")
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
                    url1 = self.base_url_template.format(date_code=date_code, hex1=hex1, hex2=hex2)
                    urls_to_check.append(url1)
                    if hex1 != hex2:
                        url2 = self.base_url_template.format(date_code=date_code, hex1=hex2, hex2=hex1)
                        urls_to_check.append(url2)
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
        """使用正则表达式提取文本中所有独立的 Emoji 序列"""
        # 注意：这个正则可能不完美，特别是对于组合或新型 Emoji
        return EMOJI_PATTERN.findall(text)

    # --- 内部处理合成并发送结果的方法 ---
    async def _process_and_send_mix(self, event: AstrMessageEvent, emoji1: str, emoji2: str):
        """内部方法，用于执行合成查找并发送结果"""
        logger.info(f"检测到混合请求: {emoji1} 和 {emoji2} (来自: {event.get_sender_name()})")
        try:
            result_url = await self._find_emoji_kitchen_url_async(emoji1, emoji2)
        except Exception as e:
            logger.error(f"执行 Emoji Kitchen URL 查找时发生意外错误: {e}", exc_info=True)
            result_url = None

        if result_url:
            # --- 修改点：直接发送图片 ---
            logger.info(f"成功合成 {emoji1} + {emoji2}，发送图片: {result_url}")
            yield event.chain_result([Comp.Image.fromURL(result_url)])
        else:
            # 失败逻辑保持不变
            response_text = f"😟 抱歉，无法找到 {emoji1} 和 {emoji2} 的混合 Emoji。\n可能是这对组合不存在，或者输入的不是有效的单个 Emoji 哦。"
            logger.info(f"未能找到 {emoji1} + {emoji2} 的混合 Emoji。")
            yield event.plain_result(response_text)

    # --- 命令处理 (优先级较高) ---
    @filter.command("mixemoji", alias={"合成emoji", "emojimix"}, priority=1) # 设置较高优先级
    async def mix_emoji_command(self, event: AstrMessageEvent):
        # 1. 获取命令后的所有文本
        input_text = event.message_str.strip() # 使用 event.message_str 获取命令后的内容
        if not input_text:
            yield event.plain_result("🤔 请在命令后提供两个 Emoji 来合成。\n例如: `/mixemoji 😂👍`")
            return

        # 2. 尝试提取文本中的所有 Emoji
        emojis = self._extract_emojis_from_text(input_text)

        # 3. 验证是否恰好提取到两个 Emoji，并且原始输入主要就是这两个 Emoji
        if len(emojis) == 2:
            # 进一步检查：移除这两个 Emoji 后，剩余部分是否为空或仅包含空格
            text_without_emojis = input_text
            # 确保按原样替换，避免内部字符干扰，只替换一次
            # 按找到的顺序替换可能更安全
            temp_text = text_without_emojis.replace(emojis[0], '', 1)
            temp_text = temp_text.replace(emojis[1], '', 1)

            # 如果移除 emoji 后，剩余部分去除空格后为空，则认为是有效输入
            if not temp_text.strip():
                emoji1 = emojis[0]
                emoji2 = emojis[1]

                logger.info(f"命令 /mixemoji 解析成功: emoji1='{emoji1}', emoji2='{emoji2}'")

                # 调用内部处理方法
                async for result in self._process_and_send_mix(event, emoji1, emoji2):
                    yield result

            else:
                # 提取到两个 Emoji，但原始输入包含其他非空格字符
                logger.warning(f"命令 /mixemoji 输入 '{input_text}' 包含除两个 Emoji 和空格外的其他字符: '{temp_text.strip()}'")
                yield event.plain_result(f"🤔 请确保命令后只提供两个 Emoji (可以有空格分隔)。检测到额外字符: '{temp_text.strip()}'")

        elif len(emojis) == 1:
             # 只提取到一个 Emoji
            logger.warning(f"命令 /mixemoji 输入 '{input_text}' 只包含一个 Emoji。")
            yield event.plain_result("🤔 检测到只有一个 Emoji，请提供两个 Emoji 来合成。")
        elif len(emojis) > 2:
             # 提取到超过两个 Emoji
            logger.warning(f"命令 /mixemoji 输入 '{input_text}' 包含超过两个 Emoji。")
            yield event.plain_result("🤔 检测到超过两个 Emoji，请只提供两个 Emoji 来合成。")
        else:
            # 没有提取到 Emoji
            logger.warning(f"命令 /mixemoji 输入 '{input_text}' 未检测到有效的 Emoji。")
            yield event.plain_result("🤔 未能在输入中检测到有效的 Emoji，请提供两个 Emoji。")
        event.stop_event()

    # --- 新增：自动检测双 Emoji 消息 (优先级较低) ---
    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1) # 设置较低优先级
    async def handle_double_emoji_message(self, event: AstrMessageEvent):
        # 3. 提取消息内容
        message_text = event.get_message_str().strip()
        if not message_text: # 忽略空消息
            return

        # 4. 尝试提取 Emoji
        emojis = self._extract_emojis_from_text(message_text)

        # 5. 判断是否恰好是两个 Emoji，且原消息基本就是这两个 Emoji 组成
        if len(emojis) == 2:
            # 进一步检查，去除所有非 Emoji 字符后是否为空，或者只剩空格
            text_without_emojis = message_text
            for e in emojis:
                text_without_emojis = text_without_emojis.replace(e, '', 1) # 替换一次，防止emoji内部字符被误删

            if not text_without_emojis.strip(): # 如果移除 emojis 后只剩空格或为空
                emoji1 = emojis[0]
                emoji2 = emojis[1]

                logger.debug(f"自动检测到双 Emoji 消息: '{emoji1}' 和 '{emoji2}'")
                # 调用内部处理方法
                async for result in self._process_and_send_mix(event, emoji1, emoji2):
                    yield result
                # 处理完成后，停止事件传播，避免干扰 LLM 或其他插件
                event.stop_event()
            else:
                logger.debug(f"提取到两个 Emoji，但原消息包含其他字符: '{message_text}' -> '{text_without_emojis}'")
