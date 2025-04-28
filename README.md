# astrbot_plugin_emojimix

# 简介
一个用于 AstrBot 的插件，实现类似Google Emoji Kitchen的效果。可由指令触发，也支持自动检测双emoji消息。

# 使用
指令触发：

    /emojimix <emoji1><emoji2>
或自动检测触发，如下图（右）
![alt](https://eimg.flartiny.cloudns.ch/i/2025/04/28/vxz4ro-0.png)
# 配置
配置中date_codes从[metadata.json](https://raw.githubusercontent.com/xsalazar/emoji-kitchen-backend/main/app/metadata.json)解析而来，不定时更新，如需主动解析，代码如下可供参考
```python
# wget https://raw.githubusercontent.com/xsalazar/emoji-kitchen-backend/main/app/metadata.json -O metadata.json
import re
import json


def extract_datecodes_from_text(json_file_path):
    with open(json_file_path, "r", encoding="utf-8") as f:
        text = f.read()
    pattern = r"emojikitchen/(\d+)"
    datecodes = set(re.findall(pattern, text))
    return sorted(datecodes)


if __name__ == "__main__":
    datecodes = extract_datecodes_from_text("metadata.json")
    print("找到的 datecode 列表:")
    for code in datecodes:
        print(code)
```

# 支持

[帮助文档](https://astrbot.app)
