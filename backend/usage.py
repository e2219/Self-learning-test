"""Credential-free request ledger; prices are versioned estimates, never a bill."""
import json
from contextvars import ContextVar
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
import httpx
from . import db

_current = ContextVar('usage_event', default=None)
PRICE_VERSION = 'DeepSeek USD / 1M · 2026-10-10 · off-peak–peak'
RATES = {'deepseek-flash': [0.15, 0.003, 0.6], 'deepseek-v4-pro': [0.66, 0.022, 1.98]}


def compact_schema(schema):
    if isinstance(schema, list): return [compact_schema(v) for v in schema]
    if not isinstance(schema, dict): return schema
    return {k: ({name:compact_schema(child) for name,child in v.items()} if k in ('properties','$defs') else compact_schema(v)) for k,v in schema.items() if k not in ('title','description','default')}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def update(event_id, **values):
    if event_id and values:
        db.execute(f"UPDATE usage_events SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), event_id))


def start(owner_type, owner_id, stage, attempt=1, question_id=None):
    if not owner_id: return None
    with db.connection() as con:
        if question_id:
            prior=con.execute('SELECT count(*) FROM usage_events WHERE owner_type=? AND owner_id=? AND question_id=? AND stage=?', (owner_type,owner_id,question_id,stage)).fetchone()[0]
            attempt=max(attempt, prior+1)
        row=con.execute('''INSERT INTO usage_events(owner_type,owner_id,stage,attempt,model,created_at,question_id,outcome)
            VALUES (?,?,?,?,?,?,?,'started')''', (owner_type,owner_id,stage,attempt,'',datetime.now(timezone.utc).isoformat(),question_id))
        return row.lastrowid


def describe_current(profile, body):
    """Called with the SAME profile snapshot used for endpoint and Authorization."""
    event_id = _current.get()
    if not event_id: return
    price = None
    if profile.get('builtin'):
        price = {'version':PRICE_VERSION, 'rates':RATES, 'factor':2}
    elif all(profile.get(k) is not None for k in ('input_price','cached_price','output_price')):
        price = {'version':'用户配置 USD / 1M', 'rates':{'*':[profile[k] for k in ('input_price','cached_price','output_price')]}, 'factor':1}
    url=urlsplit(profile['base_url'])
    update(event_id, requested_model=profile['model'], provider_origin=f'{url.scheme}://{url.netloc}',
        thinking=body.get('thinking',{}).get('type','provider_default'),
        price_version=price['version'] if price else None, price_snapshot=dumps(price) if price else None)


def valid_count(value):
    return value if type(value) is int and value >= 0 else None


def capture(event_id, data):
    if not event_id: return
    data = data if isinstance(data,dict) else {}
    u = data.get('usage') if isinstance(data.get('usage'),dict) else {}
    details=u.get('completion_tokens_details') or {}
    input_details=u.get('prompt_tokens_details') or {}
    cached=valid_count(u.get('prompt_cache_hit_tokens'))
    if cached is None and isinstance(input_details,dict): cached=valid_count(input_details.get('cached_tokens'))
    values=dict(model=str(data.get('model') or '')[:150], input_tokens=valid_count(u.get('prompt_tokens')),
        output_tokens=valid_count(u.get('completion_tokens')), cached_tokens=cached,
        total_tokens=valid_count(u.get('total_tokens')),
        reasoning_tokens=valid_count(details.get('reasoning_tokens')) if isinstance(details,dict) else None)
    row=db.one('SELECT price_snapshot FROM usage_events WHERE id=?',(event_id,))
    price=json.loads(row['price_snapshot']) if row and row['price_snapshot'] else None
    if price and all(values[k] is not None for k in ('input_tokens','output_tokens','cached_tokens')) and cached <= values['input_tokens']:
        rates=price['rates'].get(values['model'], price['rates'].get('*'))
        if rates:
            low=((values['input_tokens']-cached)*rates[0]+cached*rates[1]+values['output_tokens']*rates[2])/1e6
            values.update(estimated_usd_min=low, estimated_usd_max=low*price['factor'])
    update(event_id, **values)


async def request(client, body, role='text', *, owner_type, owner_id, stage, attempt=1, question_id=None):
    from . import providers
    event_id=start(owner_type,owner_id,stage,attempt,question_id)
    token=_current.set(event_id)
    try:
        response=await providers.complete(client,body,role)
        response.extensions['usage_event_id']=event_id
        # Provider request IDs only; never persist headers, error bodies or prompts.
        request_id=response.headers.get('x-request-id') or response.headers.get('request-id')
        update(event_id,http_status=response.status_code,request_id=request_id[:200] if request_id else None,
            outcome='received' if response.status_code==200 else 'http_error',
            error_code=None if response.status_code==200 else f'HTTP_{response.status_code}')
        try:
            data=response.json()
        except (ValueError,UnicodeError):
            if response.status_code == 200:
                update(event_id,outcome='invalid_json',error_code='HTTP_JSON')
        else:
            capture(event_id,data)
            if isinstance(data,dict) and isinstance(data.get('choices'),list) and data['choices']:
                first=data['choices'][0]
                if isinstance(first,dict) and first.get('finish_reason')=='length':
                    update(event_id,outcome='truncated',error_code='OUTPUT_LIMIT')
        return response
    except httpx.TimeoutException:
        update(event_id,outcome='timeout',error_code='TIMEOUT'); raise
    except httpx.HTTPError:
        update(event_id,outcome='network_error',error_code='NETWORK'); raise
    except Exception as exc:
        # No exception message: it could contain a URL, credential or body.
        update(event_id,outcome='client_error',error_code=type(exc).__name__[:80]); raise
    finally:
        _current.reset(token)


def decode(response):
    data=response.json()
    if isinstance(data,dict): data['_usage_event_id']=response.extensions.get('usage_event_id')
    return data


def finish(data, outcome, code=None):
    if isinstance(data,dict): update(data.get('_usage_event_id'),outcome=outcome,error_code=code)


def record(owner_type, owner_id, stage, data, attempt=1):
    """For imported/test-only reported usage without a transport profile."""
    event_id=start(owner_type,owner_id,stage,attempt)
    capture(event_id,data)
    update(event_id,outcome='received')


AGGREGATE = '''SELECT stage,count(*) AS calls,sum(input_tokens) AS input_tokens,
    sum(output_tokens) AS output_tokens,sum(cached_tokens) AS cached_tokens,
    group_concat(DISTINCT nullif(model,'')) AS models,sum(reasoning_tokens) AS reasoning_tokens,
    group_concat(DISTINCT requested_model) AS requested_models,group_concat(DISTINCT thinking) AS thinking_modes,
    sum(input_tokens IS NULL OR output_tokens IS NULL OR cached_tokens IS NULL) AS incomplete_calls,
    sum(total_tokens) AS total_tokens,sum(total_tokens IS NULL) AS unreported_calls,
    sum(attempt>1) AS retry_calls, sum(estimated_usd_min) AS estimated_usd_min,
    sum(estimated_usd_max) AS estimated_usd_max,sum(estimated_usd_min IS NULL) AS unpriced_calls,
    group_concat(DISTINCT price_version) AS price_versions,
    sum(outcome IN ('http_error','invalid_json','truncated','timeout','network_error','client_error','interrupted','rejected')) AS failed_calls
    FROM usage_events'''


def spent(owner_type, owner_id):
    return db.one('SELECT coalesce(sum(total_tokens),0) n FROM usage_events WHERE owner_type=? AND owner_id=?', (owner_type,owner_id))['n']


def reconcile(owner_type, owner_id):
    table = {'exam':'exams','plan':'exam_plans','ocr':'ocr_jobs'}[owner_type]
    db.execute(f'UPDATE {table} SET tokens=max(tokens,?) WHERE id=?', (spent(owner_type,owner_id),owner_id))


def summary(owner_type, owner_id):
    return db.rows(AGGREGATE+' WHERE owner_type=? AND owner_id=? GROUP BY stage',(owner_type,owner_id))


def ledger(start_date='', end_date=''):
    for value in (start_date,end_date):
        if value and (len(value)!=10 or date.fromisoformat(value).isoformat()!=value): raise ValueError('date')
    if start_date and end_date and start_date>end_date: raise ValueError('order')
    where=[];args=[]
    if start_date: where.append('date(created_at)>=?');args.append(start_date)
    if end_date: where.append('date(created_at)<=?');args.append(end_date)
    clause=' WHERE '+' AND '.join(where) if where else ''
    recent=db.rows('''SELECT id,created_at,owner_type,owner_id,question_id,stage,requested_model,model,
        thinking,provider_origin,request_id,http_status,outcome,error_code,total_tokens,
        estimated_usd_min,estimated_usd_max,price_version FROM usage_events'''+clause+' ORDER BY id DESC LIMIT 50',args)
    return {'rows':db.rows(AGGREGATE+clause+' GROUP BY stage',args), 'recent':recent,
        'undated_calls':db.one('SELECT count(*) n FROM usage_events WHERE created_at IS NULL')['n'],
        'timezone':'UTC', 'price_version':PRICE_VERSION}
