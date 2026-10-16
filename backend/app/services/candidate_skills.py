"""Conservative tool aliases and literal use declarations, without a model."""
import re


_TOOLS = (
    (r"photoshop|ps", "Photoshop"), (r"illustrator", "Illustrator"),
    (r"excel|exce", "Excel"), (r"powerpoint|pptl|ppt", "PPT"),
    (r"word", "Word"), (r"workbuddy", "WorkBuddy"),
    (r"即梦", "即梦"), (r"canva", "Canva"), (r"可画", "可画"), (r"剪映", "剪映"),
    (r"产品拍摄|日常摄影|摄影", "摄影"),
)
_USE = re.compile(r"能|会(?:使用|用)?|使用|用过|运用|用了|用|了解|基础|熟悉|掌握|精通|拍摄|摄影")
_LEVEL = re.compile(r"精通|熟练(?:使用)?|熟悉|掌握|会一点|会点|会使用|会用|用过|使用过|了解|基础")
_NAMES = ("Photoshop", "Illustrator", "Excel", "PPT", "Word", "WorkBuddy", "即梦", "Canva", "可画", "剪映", "摄影", "产品拍摄", "SQL",
          "Java", "Git", "Redis", "Kubernetes", "Spring Boot", "MySQL", "Python", "Figma", "Auto Layout", "Agent", "RAG")


def skill_identity(value: str) -> str:
    value = canonical_skill_text(value)
    if match := re.match(r'^(Python|Figma)(?=能)', value, re.I):
        return match[1].casefold()
    if re.match(r'^SQL仅基础查询$', value, re.I):
        return 'sql'
    value = re.sub(r'[（(](?:' + _LEVEL.pattern + r')[）)]', '', value)
    value = re.sub(r'\s+', '', re.sub(r'^(?:' + _LEVEL.pattern + r')\s*', '', value)).casefold()
    if re.fullmatch(r'agent工具调用与rag(?:基本流程|基础流程)?', value):
        return 'agent工具调用与rag'
    return value


def sourced_skill_name(name: str, evidence: str) -> str:
    """Restore a literal qualifier even if extraction returned only the tool name."""
    from app.services.fact_guard import _skill_affirmed
    canonical = canonical_skill_text(evidence)
    core = re.sub(r'[（(](?:' + _LEVEL.pattern + r')[）)]', '', canonical_skill_text(name))
    core = re.sub(r'^(?:' + _LEVEL.pattern + r')\s*', '', core).strip()
    levels = []
    for clause in re.split(r'[，,。；;\n]', canonical):
        clause = re.sub(r'^.*?【技能】', '', clause).strip()
        if (skill_identity(name) == 'agent工具调用与rag' and skill_identity(clause) == skill_identity(name)
                and re.search(r'基本流程|基础流程', clause)):
            return clause
        if not core or not _skill_affirmed(clause, core):
            continue
        if (name.strip() == clause and re.search(r'Agent|RAG', clause, re.I)
                and re.search(r'工具调用|基本流程|基础流程', clause)):
            return name
        if core.upper() == 'SQL' and re.search(r'SQL.{0,70}基础查询', clause, re.I):
            return 'SQL仅基础查询'
        if re.fullmatch(re.escape(core) + r'能[^，,。；;\n]{1,45}', clause.strip(), re.I):
            return clause.strip()
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


def apply_literal_skill_limits(collected: dict, data: dict, instruction: str) -> list[str]:
    """Apply a supplied skill ceiling to both facts and the current document."""
    changes = []
    for match in re.finditer(r'[「“"]([A-Za-z][A-Za-z0-9 +#.-]*)(仅[^」”"\n]{1,40})[」”"]', instruction):
        tool, suffix = match[1].strip(), match[2]
        if not re.search(r'写出|写明|改为|改成|必须|明确', instruction[:match.start()]):
            continue
        replacement = tool + suffix
        pattern = re.compile(r'(?<![A-Za-z0-9])' + re.escape(tool) + r'(?![A-Za-z0-9])', re.I)
        if not any(pattern.search(str(row.get('name', '') if isinstance(row, dict) else row))
                   for row in collected.get('skills', [])):
            continue
        for container in (collected, data):
            for index, row in enumerate(container.get('skills', [])):
                value = row.get('name', '') if isinstance(row, dict) else row
                if pattern.search(str(value)):
                    container['skills'][index] = ({**row, 'name': replacement, 'source_quote': replacement}
                                                  if isinstance(row, dict) else replacement)
        for values in (data.get('skill_groups') or {}).values():
            for index, value in enumerate(values):
                if pattern.search(value):
                    values[index] = replacement
        changes.append(replacement)
    return changes


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
        if (re.match(r'^\s*(?:了解|熟悉|掌握)', canonical)
                and re.search(r'Agent|RAG', canonical, re.I)
                and re.search(r'工具调用|基本流程|基础流程', canonical)
                and not re.search(r'不会|没有|不熟悉|不了解|未掌握', canonical)):
            rows.append({'name': canonical.strip(), 'source_quote': clause.strip()})
            inherited_level = None
            continue
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
            rows.append({"name": sourced_skill_name(display, clause), "source_quote": clause.strip()})
    return rows
