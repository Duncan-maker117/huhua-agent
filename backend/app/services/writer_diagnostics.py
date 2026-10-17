"""Per-line evidence and failures, shared by labeled body and project headings."""


def failure(code: str, *, category: str = '', **detail) -> dict:
    if not category:
        if 'number' in code or 'quantity' in code:
            category = '数字'
        elif 'tool' in code or 'object' in code or 'subject' in code or 'experience' in code:
            category = '实体'
        elif 'negative' in code or 'absence' in code:
            category = '否定'
        elif 'limit' in code or 'frequency' in code or 'manner' in code or 'scope' in code:
            category = '限定'
        elif 'status' in code or 'result' in code:
            category = '状态'
        elif 'action' in code or 'purpose' in code or 'effect' in code:
            category = '动作'
        elif 'coverage' in code or 'semantic' in code or 'retention' in code:
            category = '语义覆盖'
        else:
            category = '其他'
    return {'category': category, 'code': code, **detail}


def verdict_failures(verdict: dict, **detail) -> list[dict]:
    errors = [failure(code, **detail) for code in verdict.get('lexical_errors', [])]
    semantic = verdict.get('semantic') or {}
    for key in ('subject_ok', 'actions_supported', 'objects_supported', 'results_supported', 'limits_kept'):
        if semantic.get(key) is False:
            errors.append(failure(key, **detail))
    errors.extend(failure('semantic_unsupported_span', span=span, **detail)
                  for span in semantic.get('unsupported_spans', []))
    if verdict.get('verdict') == 'fail' and not errors:
        errors.append(failure('semantic_rejected', **detail))
    return errors


def line_trace(diagnostic: dict, item_id: str, slot: str, ids: list[str]) -> dict:
    record = {'item_id': item_id, 'slot': slot, 'selected_fact_ids': list(ids),
              'attempts': [], 'retry_count': 0, 'final_handling': 'pending',
              'final_text': '', 'final_fact_ids': []}
    diagnostic.setdefault('slot_lines', {})[item_id + ':' + slot] = record
    return record


def attempt(trace: dict, stage: str, text: str, ids: list[str], verdict: dict,
            *, model_rows=()) -> None:
    trace['attempts'].append({'stage': stage, 'text': text, 'fact_ids': list(ids),
                             'model_rows': list(model_rows), **verdict})


def delivered(trace: dict, row: dict, handling: str) -> None:
    trace.update(final_handling=handling, final_text=row['text'], final_fact_ids=list(row['fact_ids']))
