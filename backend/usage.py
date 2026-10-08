"""Persist provider-reported usage only; no inferred prices or raw course content."""
import json
from . import db


def compact_schema(schema):
    if isinstance(schema, list):
        return [compact_schema(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    return {k: ({name:compact_schema(child) for name,child in v.items()} if k in ('properties','$defs') else compact_schema(v)) for k, v in schema.items() if k not in ('title', 'description', 'default')}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def record(owner_type, owner_id, stage, data, attempt=1):
    if not owner_id:
        return
    usage = data.get('usage') if isinstance(data, dict) else None
    if not isinstance(usage, dict): usage = {}
    def count(key):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    db.execute('INSERT INTO usage_events(owner_type,owner_id,stage,attempt,model,input_tokens,output_tokens,cached_tokens,total_tokens) VALUES (?,?,?,?,?,?,?,?,?)',
        (owner_type, owner_id, stage, attempt, str(data.get('model') or ''), count('prompt_tokens'), count('completion_tokens'), count('prompt_cache_hit_tokens'), count('total_tokens')))


def summary(owner_type, owner_id):
    return db.rows('''SELECT stage,count(*) AS calls,sum(input_tokens) AS input_tokens,
        sum(output_tokens) AS output_tokens,sum(cached_tokens) AS cached_tokens,
        sum(total_tokens) AS total_tokens,sum(total_tokens IS NULL) AS unreported_calls,
        sum(attempt>1) AS retry_calls FROM usage_events WHERE owner_type=? AND owner_id=? GROUP BY stage''', (owner_type, owner_id))
