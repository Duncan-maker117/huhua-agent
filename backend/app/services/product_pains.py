"""Literal product-problem evidence; never turn an editing request into a fact."""
import re


def product_pain(text: str) -> bool:
    if re.search(r'^(?:请|帮我|给我|不要|别|把|将)|我(?:也)?不知道|[？?]', text.strip()):
        return False
    return bool(re.search(r'用户|学生|工具|(?:通用|普通|现有).*方案|AI|ai|简历', text)
                and re.search(r'繁琐|繁杂|痛点|难以|不会|无法|不能|不懂|不知道|复制粘[贴体]|一个一个填', text))


def pain_clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r'[。；;\n]|\s+(?=甚至)', text)
            if product_pain(part.strip())]


def recover_product_pains(result: dict, evidence: str, outline: list[dict], turn_id: str) -> None:
    from app.services.resume_facts import new_fact
    candidates = {row['item_id']: row for row in [*outline, *result['items']]
                  if row['section'] == 'projects'}
    clauses = pain_clauses(evidence)
    for clause in clauses:
        named = [row for row in candidates.values() if row.get('name') and row['name'] in clause]
        # Unnamed problem-first narratives are common. Bind only when the
        # current message establishes exactly one project, never across peers.
        current = {row['item_id']: row for row in result['items'] if row['section'] == 'projects'}
        owners = named or list(current.values()) or list(candidates.values())
        if len(owners) != 1:
            continue
        owner = owners[0]
        existing = [*owner.get('facts', []), *candidates[owner['item_id']].get('facts', [])]
        if any(re.sub(r'^(?:解决了|甚至)', '', clause).strip() ==
               re.sub(r'^(?:解决了|甚至)', '', str(f.get('source_quote') or '')).strip()
               and f.get('kind') == 'context' for f in existing):
            continue
        patch = next((row for row in result['items'] if row['item_id'] == owner['item_id']), None)
        if patch is None:
            patch = {**owner, 'facts': [], 'raw_notes': []}
            result['items'].append(patch)
        # Keep the exact quote. “解决了…” describes the motivation, not proof
        # that this candidate eliminated the pain for all users.
        text = re.sub(r'^(?:解决了|甚至)', '', clause).strip()
        patch['facts'].append(new_fact(text, kind='context', quote=clause, source='chat', turn_id=turn_id))
