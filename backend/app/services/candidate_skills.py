"""Conservative tool aliases and literal use declarations, without a model."""
import re


_TOOLS = (
    (r"photoshop|ps", "Photoshop"), (r"illustrator", "Illustrator"),
    (r"excel|exce", "Excel"), (r"powerpoint|pptl|ppt", "PPT"),
    (r"word", "Word"), (r"workbuddy", "WorkBuddy"),
    (r"即梦", "即梦"), (r"canva", "Canva"), (r"可画", "可画"), (r"剪映", "剪映"),
    (r"产品拍摄|日常摄影|摄影", "摄影"),
)
_USE = re.compile(r"会(?:使用|用)?|使用|用过|运用|用了|用|了解|基础|熟悉|掌握|精通|拍摄|摄影")
_LEVEL = re.compile(r"精通|熟练(?:使用)?|熟悉|掌握|会一点|会点|会使用|会用|用过|使用过|了解|基础")
_NAMES = ("Photoshop", "Illustrator", "Excel", "PPT", "Word", "WorkBuddy", "即梦", "Canva", "可画", "剪映", "摄影", "产品拍摄",
          "Java", "Git", "Redis", "Kubernetes", "Spring Boot", "MySQL", "Python", "Figma", "Auto Layout")


def skill_identity(value: str) -> str:
    value = canonical_skill_text(value)
    value = re.sub(r'[（(](?:' + _LEVEL.pattern + r')[）)]', '', value)
    return re.sub(r'\s+', '', re.sub(r'^(?:' + _LEVEL.pattern + r')\s*', '', value)).casefold()


def sourced_skill_name(name: str, evidence: str) -> str:
    """Restore a literal qualifier even if extraction returned only the tool name."""
    from app.services.fact_guard import _skill_affirmed
    canonical = canonical_skill_text(evidence)
    core = re.sub(r'[（(](?:' + _LEVEL.pattern + r')[）)]', '', canonical_skill_text(name))
    core = re.sub(r'^(?:' + _LEVEL.pattern + r')\s*', '', core).strip()
    levels = []
    for clause in re.split(r'[，,。；;\n]', canonical):
        if not core or not _skill_affirmed(clause, core):
            continue
        for match in re.finditer(re.escape(core), clause, re.I):
            prefix = clause[:match.start()]
            found = list(_LEVEL.finditer(prefix))
            suffix = re.match(r'\s*[（(](' + _LEVEL.pattern + r')[）)]', clause[match.end():])
            if suffix or found:
                level = suffix[1] if suffix else found[-1][0]
                if level in {'会一点', '会点', '基础'}:
                    levels.append(('基础', 0))
                elif level in {'了解', '熟悉', '掌握', '精通', '熟练', '熟练使用'}:
                    levels.append((level, {'了解': 0, '熟悉': 1, '掌握': 2}.get(level, 3)))
    if levels:
        return core + '（' + min(levels, key=lambda pair: pair[1])[0] + '）'
    return name


def skill_declaration(text: str) -> bool:
    """Tool ability alone is a skill; a concrete delivery is also an experience."""
    return bool(re.search(r"会|了解|基础|熟悉|掌握|精通|使用|运用|用过|用了", text) and declared_skills(text) and not re.search(
        r"作业|课程|课上|做(?:了|过|出)|完成|制作|设计(?:了|过)|海报|产品图|排版|拍摄|开发|负责|交付|上线|整理|处理|分析|统计", text))


def canonical_skill_text(text: str) -> str:
    """AI means Illustrator only in the same design/PS clause."""
    parts = re.split(r"([。；;\n])", str(text or ""))
    for index in range(0, len(parts), 2):
        clause = parts[index]
        design = re.search(r"(?<![a-z])ps(?![a-z])|photoshop|设计", clause, re.I)
        if design:
            clause = re.sub(r"(?<![a-z0-9])ai(?![a-z0-9])", "Illustrator", clause, flags=re.I)
        for pattern, name in _TOOLS:
            if name == "摄影":
                continue
            clause = re.sub(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", name, clause, flags=re.I)
        parts[index] = clause
    return "".join(parts)


def declared_skills(text: str) -> list[dict]:
    from app.services.fact_guard import _skill_affirmed
    from app.services.candidate_language import non_fact
    rows = []
    original = re.split(r"[，,。；;\n]", str(text or ""))
    canonical_clauses = re.split(r"[，,。；;\n]", canonical_skill_text(text))
    inherited_level = None
    for clause, canonical in zip(original, canonical_clauses):
        # A comma-separated tool list inherits its declaration, not a delivery.
        bare_tool = bool(re.fullmatch(r"\s*(?:" + '|'.join(map(re.escape, _NAMES)) + r")\s*", canonical, re.I))
        if non_fact(clause) or (not _USE.search(clause) and not (bare_tool and inherited_level is not None)):
            inherited_level = None
            continue
        names = _NAMES
        for name in sorted(names, key=lambda name: canonical.casefold().find(name.casefold())):
            if not _skill_affirmed(canonical, name):
                continue
            before = canonical[:canonical.casefold().find(name.casefold())]
            levels = list(_LEVEL.finditer(before))
            level = levels[-1][0] if levels else (inherited_level or "")
            inherited_level = level
            display = name + "（基础）" if level in {"会一点", "会点", "基础"} else ("" if level in {"会用", "会使用"} else level) + name
            rows.append({"name": display, "source_quote": clause.strip()})
    return rows
