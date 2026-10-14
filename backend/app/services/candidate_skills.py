"""Conservative tool aliases and literal use declarations, without a model."""
import re


_TOOLS = (
    (r"photoshop|ps", "Photoshop"), (r"illustrator", "Illustrator"),
    (r"excel|exce", "Excel"), (r"powerpoint|pptl|ppt", "PPT"),
    (r"word", "Word"), (r"workbuddy", "WorkBuddy"),
    (r"即梦", "即梦"), (r"可画|canva", "可画"),
    (r"产品拍摄|日常摄影|摄影", "摄影"),
)
_USE = re.compile(r"会(?:使用|用)?|使用|用过|运用|用了|用|熟悉|掌握|精通|拍摄|摄影")
_LEVEL = re.compile(r"精通|熟练(?:使用)?|熟悉|掌握|会使用|会用|用过|使用过|了解|基础")


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
    rows = []
    original = re.split(r"[，,。；;\n]", str(text or ""))
    canonical_clauses = re.split(r"[，,。；;\n]", canonical_skill_text(text))
    for clause, canonical in zip(original, canonical_clauses):
        if not _USE.search(clause):
            continue
        names = ("Photoshop", "Illustrator", "Excel", "PPT", "Word", "WorkBuddy", "即梦", "可画", "摄影", "产品拍摄")
        for name in sorted(names, key=lambda name: canonical.casefold().find(name.casefold())):
            if not _skill_affirmed(canonical, name):
                continue
            before = canonical[:canonical.casefold().find(name.casefold())]
            levels = list(_LEVEL.finditer(before))
            level = levels[-1][0] if levels else ""
            rows.append({"name": level + name, "source_quote": clause.strip()})
    return rows
