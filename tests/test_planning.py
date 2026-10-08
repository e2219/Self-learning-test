import copy
import json

import httpx
import pytest

from backend import db, generation, planning
from tests.test_api import client, setup, exam_config, fake_generate  # noqa: F401
from tests.test_generation_recovery import result


def planner(monkeypatch, corrupt=False):
    original = httpx.AsyncClient
    def handler(request):
        data = json.loads(json.loads(request.content)['messages'][1]['content'])
        ref = data['sources'][0]
        return httpx.Response(200, json=result({'topics': [{'title': '事件独立性', 'objective': '根据独立性计算联合概率', 'evidence_id': 'forged' if corrupt else ref['id']+':0'}]}))
    monkeypatch.setattr(planning.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def create_plan(client, setup):
    created = client.post('/api/exam-plans', json=exam_config(setup))
    assert created.status_code == 201
    return client.get('/api/exam-plans/'+created.json()['id']).json()


def test_plan_to_exam_persists_editable_targets_and_coverage(client, setup, monkeypatch):
    planner(monkeypatch)
    plan = create_plan(client, setup)
    assert plan['status'] == 'ready' and plan['tokens'] == 100 and len(plan['blueprint']) == 2
    config = {**exam_config(setup), 'plan_id': plan['id'], 'blueprint': plan['blueprint']}
    config['blueprint'][0]['objective'] = '核对事件独立性的条件'
    seen = []
    async def generate(q, config, refs, previous):
        seen.append((config['planned_target'], refs))
        return await fake_generate(q, config, refs, previous)
    monkeypatch.setattr(generation, 'generate_one', generate)
    response = client.post('/api/exams', json=config)
    assert response.status_code == 201
    exam = client.get('/api/exams/'+response.json()['id']).json()
    assert exam['status'] == 'ready' and exam['planning_tokens'] == 100 and exam['tokens'] == 200
    assert exam['coverage'] == [{'title': '事件独立性', 'planned': 2, 'completed': 2}]
    assert seen[0][0]['objective'] == '核对事件独立性的条件'
    assert seen[0][1][0]['page'] == 1


def test_source_change_invalidates_plan_and_topic_ids_cannot_be_forged(client, setup, monkeypatch):
    planner(monkeypatch); plan = create_plan(client, setup)
    config = {**exam_config(setup), 'plan_id': plan['id'], 'blueprint': copy.deepcopy(plan['blueprint'])}
    config['blueprint'][0]['topic_id'] = 'forged'
    assert client.post('/api/exams', json=config).status_code == 422
    config['blueprint'] = plan['blueprint']
    client.put(f"/api/documents/{setup[1]['id']}/pages/1", json={'text': '已修改的教材。'*20})
    response = client.post('/api/exams', json=config)
    assert response.status_code == 422 and '变化' in response.json()['detail']


def test_bad_evidence_fails_with_usage_retained(client, setup, monkeypatch):
    planner(monkeypatch, corrupt=True); plan = create_plan(client, setup)
    assert plan['status'] == 'failed' and plan['tokens'] == 100
    assert '引用' in plan['error']


def test_blueprint_types_points_and_count_must_match(client, setup, monkeypatch):
    planner(monkeypatch); plan = create_plan(client, setup)
    for patch in [{'type': 'choice'}, {'points': 99}, {'objective': '   '}]:
        slots = copy.deepcopy(plan['blueprint']); slots[0].update(patch)
        response = client.post('/api/exams', json={**exam_config(setup), 'plan_id': plan['id'], 'blueprint': slots})
        assert response.status_code == 422
    assert client.post('/api/exams', json={**exam_config(setup), 'plan_id': plan['id'], 'blueprint': plan['blueprint'][:1]}).status_code == 422


def test_explicit_focus_and_exercise_sources_have_priority():
    quote = '习题：分析米氏常数的含义，比较不同底物浓度下的反应速度。'
    batch = [{'id':'0', 'text':quote, 'document_id':'doc', 'page':1, 'kind':'习题集', 'name':'课后习题'}]
    payload = {'topics':[{'title':'米氏常数', 'objective':'比较酶促反应速度', 'evidence_id':'0:0'}]}
    topic = planning.validate_topics(payload, batch, '米氏常数')[0]
    assert '匹配指定重点' in topic['reasons'] and '习题资料' in topic['reasons']
    assert topic['weight'] > 1


def test_material_limit_fails_before_api_request(client, setup, monkeypatch):
    monkeypatch.setattr(planning, 'MAX_CHARS', 10)
    response = client.post('/api/exam-plans', json=exam_config(setup))
    assert response.status_code == 422 and '缩小范围' in response.json()['detail']


def test_every_material_batch_is_processed(client, setup, monkeypatch):
    planner(monkeypatch)
    doc = setup[1]['id']
    db.execute('UPDATE documents SET page_count=3 WHERE id=?', (doc,))
    for n in (2,3):
        db.execute('INSERT INTO pages(document_id,number,text) VALUES (?,?,?)', (doc,n, f'课后习题第{n}页讨论事件独立性及其应用。'*6))
    monkeypatch.setattr(planning, 'BATCH_CHARS', 100)
    config = exam_config(setup); config['ranges'][0]['end'] = 3
    response = client.post('/api/exam-plans', json=config)
    plan = client.get('/api/exam-plans/'+response.json()['id']).json()
    assert plan['status'] == 'ready' and plan['tokens'] == 300
    assert {s['page'] for s in plan['topics'][0]['sources']} == {1,2,3}


def test_cancellation_stops_later_batches_and_retains_usage(client, setup, monkeypatch):
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        task = json.loads(json.loads(request.content)['messages'][1]['content'])
        calls.append(task)
        db.execute("UPDATE exam_plans SET status='cancelled' WHERE status='running'")
        return httpx.Response(200, json=result({'topics':[{'title':'事件独立性','objective':'计算概率','evidence_id':task['evidence'][0]['id']}]}))
    monkeypatch.setattr(planning.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    doc=setup[1]['id']
    db.execute('UPDATE pages SET text=? WHERE document_id=?',('事件独立性需要检查乘法公式。'*400,doc))
    monkeypatch.setattr(planning,'BATCH_CHARS',3000)
    plan=create_plan(client,setup)
    assert plan['status']=='cancelled' and plan['tokens']==100 and len(calls)==1


def test_planned_retrieval_does_not_include_unassigned_nearby_topics(client, setup):
    config=exam_config(setup); doc=setup[1]['id']
    quote='酶是生物催化剂，大多数酶为蛋白质，少数具有催化活性的 RNA 也属于酶。'
    db.execute('UPDATE pages SET text=? WHERE document_id=?',(quote+'\n其他主题：米氏常数等于最大速度一半时的底物浓度。',doc))
    topic={'id':'t','title':'酶的本质','sources':[{'document_id':doc,'page':1,'quote':quote}]}
    db.execute('INSERT INTO exam_plans(id,course_id,config,fingerprint,materials,topics,status) VALUES (?,?,?,?,?,?,?)',('p',setup[0]['id'],'{}','x','[]',db.dump([topic]),'ready'))
    refs,target=planning.planned_references({**config,'plan_id':'p','blueprint':[{'topic_id':'t','objective':'酶的本质'}]},1)
    assert refs[0]['text']==quote and '米氏' not in refs[0]['text']
