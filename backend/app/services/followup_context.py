"""自由文本追问的事实归属辅助；不参与问题卡生成。"""

import re


def latest_followup(reply: str) -> str:
    """Read the latest direct question, including natural next-step prompts.

    Only the current public reply is supplied. Ignore code, block quotations
    and illustrative interview questions; compound questions remain compound
    so the option classifier can leave them as free text.
    """
    cleaned = re.sub(r"```[\s\S]*?```", "", reply)
    # Coverage notices are receipts, including when appended on the same line.
    cleaned = re.sub(r"这句(?:我没|没有)记下来[^\n]*|「[^」\n]*」后面还没说完[^\n]*", "", cleaned)
    groups, current = [], []
    numbered = []  # Parallel to groups: each numbered list item is its own question.
    current_item = False
    explicit_section = False
    for raw in cleaned.splitlines():
        line = raw.strip()
        item = bool(re.match(r"\d+[.)、]\s*", line))
        if not line or line.startswith(">") or (item and current):
            if current:
                groups.append(" ".join(current))
                numbered.append(current_item)
                current = []
            if not line or line.startswith(">"):
                continue
        if not current:
            current_item = item
        line = re.sub(r"^(?:#{1,6}\s*|[-*+]\s+|\d+[.)、]\s*)", "", line).strip(" *")
        header = re.match(r"(?:【)?(?:需要你补充|请你补充|待你补充)(?:】)?\**\s*[:：]?\s*(.*)", line)
        if header:
            explicit_section = True
            line = header.group(1).strip(" *")
            if not line:
                continue
        elif raw.lstrip().startswith(("#", "**", "【")) and not re.search(r"[？?]", line):
            explicit_section = False
        if re.match(r"(?:例如|比如|示例|举例|面试官.{0,6}问|常见问题|可以这样问)", line) or re.match(r'^[“"].*[”"]$', line):
            continue
        # The final sentence is normally addressed to the user; earlier prose
        # explains the analysis rather than requesting another fact.
        sentence = re.split(r"[。！!]\s*", line.rstrip("。！!"))[-1].strip()
        asks = bool(re.search(r"[？?]", sentence))
        next_step = bool(re.search(r"(?:还想|还有|是否|要不要|你想|接下来|可以|还是).{0,45}(?:补充|生成|整理|草稿)", sentence))
        direct_request = bool(re.match(r"(?:请|能否|麻烦你|你可以).{0,25}(?:补充|说明|描述|选择|核对)", sentence))
        if sentence and (asks or next_step or direct_request or explicit_section):
            current.append(sentence)
        elif current:
            groups.append(" ".join(current))
            numbered.append(current_item)
            current = []
    if current:
        groups.append(" ".join(current))
        numbered.append(current_item)
    if not groups:
        return ""
    # A trailing numbered list is ordered by value: ask its first question.
    last = len(groups) - 1
    while last > 0 and numbered[last] and numbered[last - 1]:
        last -= 1
    return re.sub(r"\s*[（(]会改进[:：][^）)]*[）)]\s*$", "", groups[last])[:300]


