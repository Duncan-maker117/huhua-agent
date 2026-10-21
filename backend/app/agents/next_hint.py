"""Optional model-selected intentions, never candidate facts or an extra call."""
import re


HINTS = (
    "补充一下这段实习的具体成果", "补充一下这段经历中我负责的部分",
    "补充一下这个项目的具体做法", "我想补充一段经历", "我想说明目标岗位",
    "帮我分析这份岗位要求", "帮我根据已有经历写一版简历", "帮我润色这段经历",
    "帮我换成简约模板", "帮我检查简历排版", "帮我检查哪些内容还需要核对",
    "帮我精简一下简历", "我想调整简历的求职方向",
)
HINT_PROMPT = (
    "最终文字回复后可附加 <next_hint>一句提示</next_hint>，这是输入框建议，不是正文。"
    "只能从以下用户口吻的意图句中选择一句适合下一步的；没有合适的或已展示问题卡时省略。"
    "不得增加个人事实、名称、数字或链接，不为提示另调工具：" + "；".join(HINTS)
)


def filter_next_hint(value, *, has_card=False):
    if has_card or not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 30 or re.search(r"\d|@|http", value, re.I):
        return None
    # A character denylist alone cannot reject invented employers or achievements.
    return value if value in HINTS else None


class HintStream:
    """Strip the optional structured suffix even when its marker splits tokens."""
    marker = "<next_hint>"

    def __init__(self):
        self.buffer = ""
        self.suffix = ""

    def feed(self, text):
        if self.suffix:
            self.suffix += text
            return ""
        self.buffer += text
        if self.marker in self.buffer:
            public, suffix = self.buffer.split(self.marker, 1)
            self.suffix = self.marker + suffix
            self.buffer = ""
            return public
        keep = max((n for n in range(1, len(self.marker)) if self.buffer.endswith(self.marker[:n])), default=0)
        public, self.buffer = self.buffer[:len(self.buffer) - keep], self.buffer[len(self.buffer) - keep:]
        return public

    def hint(self):
        match = re.fullmatch(r"<next_hint>([^<>]*)</next_hint>\s*", self.suffix)
        return filter_next_hint(match[1]) if match else None
