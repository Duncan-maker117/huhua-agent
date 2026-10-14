"""Small, deterministic prose triggers. The writer still owns any new wording."""
import re

from app.services.fact_guard import normalize_text


_VERB = re.compile(r"^(?:协助|参与|完成|撰写|编写|拍摄|制作|设计|排版|使用|运用|整理|管理|采购|对接|"
                   r"开发|实现|搭建|构建|优化|分析|测试|验证|维护|处理|记录|核对|支持|负责|推动|组织|"
                   r"调研|收集|提报|提交|获|建立|上线|发布|部署|修复|拆分|接入|输出|提供|基于|通过|针对|为|在|用)")
_OBJECT = re.compile(r"文章|推文|初稿|视频|素材|海报|文案|页面|接口|系统|项目|记录|报表|数据|客户|用户|"
                     r"用品|考勤|材料|反馈|报告|测试|需求|原型|文件|申请|付款")


def needs_polish(bullet: str, *, source_quotes=(), siblings=()) -> list[str]:
    """Context is optional; exact quotes and duplicates require same-item evidence."""
    from app.services.fact_coverage import text_covered
    text = str(bullet or "").strip()
    reasons = []
    # 「3篇初稿由本人撰写」 is formal attribution, not an oral first-person lead.
    if re.search(r"我(?:们)?|^本人", text):
        reasons.append("first_person")
    if re.search(r"帮.{0,10}做|(?:写|拍|做|排版|完成|制作|使用)过|[过了][。！!]?\s*$", text):
        reasons.append("colloquial")
    if len(normalize_text(text)) < 8 and not re.search(r"\d|[一二两三四五六七八九十]+(?:篇|条|张|个)", text) and not _OBJECT.search(text):
        reasons.append("short_fragment")
    # Only flag sentence-like narration. A technical noun phrase is not enough
    # evidence to reorder it deterministically or manufacture an action.
    if text and not _VERB.search(text) and re.search(r"(?:期间|时候|然后|当时|工作内容|主要是)|.{3,}(?:做|写|拍|完成|整理)", text):
        reasons.append("narrative_opening")
    if any(text_covered(text, [other]) for other in siblings if other):
        reasons.append("semantic_duplicate")
    if any(normalize_text(text) == normalize_text(quote) for quote in source_quotes if quote):
        reasons.append("verbatim_source")
    return reasons
