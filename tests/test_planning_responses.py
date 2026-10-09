import json

import httpx
import pytest

from backend import db, planning
from tests.test_api import client, setup, exam_config  # noqa: F401
from tests.test_generation_recovery import result
from tests.test_planning import create_plan


def adapter(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(planning.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def topic(task, **patch):
    return {**dict(title='事件独立性', objective='计算联合概率', evidence_id=task['evidence'][0]['id']), **patch}


def test_fenced_json_and_empty_optional_fields_need_no_paid_retry(client, setup, monkeypatch):
    calls = []
    def handler(req):
        task = json.loads(json.loads(req.content)['messages'][1]['content']); calls.append(task)
        text = '```json\n' + json.dumps({'topics':[topic(task, question_style=None, key_conditions=None)]}) + '\n```'
        return httpx.Response(200, json=result(text))
    adapter(monkeypatch, handler)
    plan = create_plan(client, setup)
    assert plan['status'] == 'ready' and plan['tokens'] == 100 and len(calls) == 1
    # Knowledge-only materials do not need reference exam metadata or its schema.
    schema = json.dumps(calls[0]['schema'])
    assert 'original_points' not in schema and 'key_conditions' not in schema


def test_reference_material_keeps_full_metadata_schema(client, setup, monkeypatch):
    def handler(req):
        task = json.loads(json.loads(req.content)['messages'][1]['content'])
        assert 'original_points' in json.dumps(task['schema'])
        return httpx.Response(200, json=result({'topics':[topic(task, question_type='choice', question_style=None, key_conditions=None)]}))
    adapter(monkeypatch, handler)
    config = exam_config(setup); config['ranges'][0]['role'] = 'reference'
    created = client.post('/api/exam-plans', json=config).json()
    plan = client.get('/api/exam-plans/'+created['id']).json()
    assert plan['status'] == 'ready'
    assert plan['topics'][0]['reference_types'] == {'choice':1}


@pytest.mark.parametrize('response,code', [
    (result('not JSON secret-source-text'), 'PLAN_JSON'),
    (result('{}', finish='length'), 'PLAN_TRUNCATED'),
    (result(None), 'PLAN_SCHEMA'),
    (result({'topics':[{'title':'secret-source-text'}]}), 'PLAN_SCHEMA'),
    (result(''), 'PLAN_EMPTY'),
    ({'choices': [], 'usage':{'total_tokens':100}}, 'PLAN_RESPONSE'),
    (result('{}', finish='content_filter'), 'PLAN_INCOMPLETE'),
    (result({'topics': []}), 'PLAN_SCHEMA'),
])
def test_specific_error_retains_usage_without_retry_or_leaking_content(client, setup, monkeypatch, caplog, response, code):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=response)
    adapter(monkeypatch, handler)
    plan = create_plan(client, setup)
    assert plan['status'] == 'failed' and plan['tokens'] == 100 and len(calls) == 1
    assert code in plan['error'] and '第 1/1 批' in plan['error']
    assert code in caplog.text and 'secret-source-text' not in caplog.text + plan['error']
    assert db.one('SELECT count(*) AS n FROM topic_cache')['n'] == 0


@pytest.mark.parametrize('failure,code', [('timeout','PLAN_TIMEOUT'),('connect','PLAN_NETWORK'),('html','PLAN_HTTP_JSON')])
def test_network_and_http_json_failures_are_distinguished(client, setup, monkeypatch, failure, code):
    def handler(req):
        if failure == 'timeout': raise httpx.ReadTimeout('private-provider-url', request=req)
        if failure == 'connect': raise httpx.ConnectError('private-provider-url', request=req)
        return httpx.Response(200, text='<html>private-provider-url</html>')
    adapter(monkeypatch, handler)
    plan = create_plan(client, setup)
    assert plan['status'] == 'failed' and code in plan['error']
    assert 'private-provider-url' not in plan['error']
    assert '未报告用量不代表未计费' in plan['error']


def test_later_batch_failure_preserves_cache_and_retry_only_requests_missing_pages(client, setup, monkeypatch):
    doc = setup[1]['id']
    db.execute('UPDATE documents SET page_count=2 WHERE id=?', (doc,))
    db.execute('INSERT INTO pages(document_id,number,text) VALUES (?,?,?)', (doc,2,'条件概率定义及其应用。'*15))
    monkeypatch.setattr(planning, 'BATCH_CHARS', 100)
    config = exam_config(setup); config['ranges'][0]['end'] = 2
    calls = []
    def handler(req):
        task = json.loads(json.loads(req.content)['messages'][1]['content']); calls.append(task)
        if len(calls) == 2: return httpx.Response(200, json=result('{broken'))
        return httpx.Response(200, json=result({'topics':[topic(task)]}))
    adapter(monkeypatch, handler)
    def run():
        created = client.post('/api/exam-plans', json=config).json()
        return client.get('/api/exam-plans/'+created['id']).json()
    first = run()
    assert first['status'] == 'failed' and first['tokens'] == 200
    assert '第 2/2 批' in first['error'] and 'PLAN_JSON' in first['error']
    second = run()
    assert second['status'] == 'ready' and second['tokens'] == 100 and second['cache_hits'] == 1
    assert len(calls) == 3 and [r['page'] for r in calls[-1]['sources']] == [2]
    assert {s['page'] for s in second['topics'][0]['sources']} == {1,2}


def test_invalid_evidence_in_fenced_response_still_rejected(client, setup, monkeypatch):
    def handler(req):
        task = json.loads(json.loads(req.content)['messages'][1]['content'])
        text = '```json\n' + json.dumps({'topics':[topic(task, evidence_id='forged')]}) + '\n```'
        return httpx.Response(200, json=result(text))
    adapter(monkeypatch, handler)
    plan = create_plan(client, setup)
    assert plan['status'] == 'failed' and '引用' in plan['error']
    assert db.one('SELECT count(*) AS n FROM topic_cache')['n'] == 0
