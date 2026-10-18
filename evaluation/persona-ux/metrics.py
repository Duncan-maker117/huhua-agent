"""Numeric-only replay telemetry; provider text and unknown fields never persist."""
import math

TOKEN_FIELDS = ('prompt_tokens', 'completion_tokens', 'reasoning_tokens', 'prompt_cache_hit_tokens')


def number(value, *, integer=False):
    valid = type(value) is int if integer else type(value) in {int, float}
    return value if valid and math.isfinite(value) and value >= 0 else None


def usage(value):
    value = value if isinstance(value, dict) else {}
    return {key: number(value.get(key), integer=True) for key in TOKEN_FIELDS}


def orchestrator(value):
    if not isinstance(value, dict):
        return None
    rows = value.get('turns')
    calls = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            calls.append({'mode': row.get('mode') if row.get('mode') in {'off', 'thinking'} else None,
                          'seconds': number(row.get('seconds')), 'usage': usage(row.get('usage'))})
    return {'model_calls': number(value.get('model_calls'), integer=True),
            'tool_steps': number(value.get('tool_steps'), integer=True),
            'seconds': number(value.get('seconds')), 'usage': usage(value.get('usage')), 'turns': calls}


def complete_sum(values):
    return sum(values) if values and all(v is not None for v in values) else None
