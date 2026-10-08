import copy
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from backend import db, drafts, planning, generation, answer_check
from backend.models import AnswerCheckInput
from tests.test_api import client, setup, exam_config, fake_generate  # noqa: F401
from tests.test_planning import planner, create_plan
from tests.test_generation_recovery import result


def save_body(plan, **config_patch):
    return {'revision':plan['revision'],'config':{**plan['config'],**config_patch},'blueprint':plan['blueprint']}


def test_restore_saved_config_blueprint_and_history_without_model_calls(client, setup, monkeypatch):
    planner(monkeypatch); plan=create_plan(client,setup)
    body=save_body(plan,title='我的恢复测试',duration=90)
    body['blueprint'][0]['objective']='人工调整的设问目标'
    saved=client.put(f"/api/exam-plans/{plan['id']}/draft",json=body).json()
    assert saved['revision']==1 and not saved['needs_replan']
    latest=client.get(f"/api/courses/{setup[0]['id']}/exam-plans/latest").json()
    assert latest['config']['title']=='我的恢复测试' and latest['config']['duration']==90
    assert latest['blueprint'][0]['objective']=='人工调整的设问目标'
    history=client.get(f"/api/exam-plans/{plan['id']}/history").json()
    assert [h['revision'] for h in history]==[1,0]
    assert history[1]['blueprint'][0]['objective']!='人工调整的设问目标'
    assert client.put(f"/api/exam-plans/{plan['id']}/draft",json=body).status_code==409


def test_changed_material_preserves_draft_and_reports_page(client, setup, monkeypatch):
    planner(monkeypatch); plan=create_plan(client,setup)
    body=save_body(plan); body['blueprint'][0]['objective']='保留我的修改'
    client.put(f"/api/exam-plans/{plan['id']}/draft",json=body)
    client.put(f"/api/documents/{setup[1]['id']}/pages/1",json={'text':'新的资料正文。'*20})
    changed=client.get(f"/api/exam-plans/{plan['id']}").json()
    assert changed['needs_replan'] and '第 1 页' in changed['source_changes'][0]['label']
    assert changed['blueprint'][0]['objective']=='保留我的修改'
    response=client.post('/api/exams',json={**plan['config'],'plan_id':plan['id'],'blueprint':plan['blueprint']})
    assert response.status_code==422 and '变化' in response.json()['detail']


def test_file_rename_does_not_invalidate_sources(client, setup, monkeypatch):
    planner(monkeypatch); plan=create_plan(client,setup)
    db.execute('UPDATE documents SET name=? WHERE id=?',('重命名教材.pdf',setup[1]['id']))
    current=client.get(f"/api/exam-plans/{plan['id']}").json()
    assert not current['needs_replan']
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    response=client.post('/api/exams',json={**plan['config'],'plan_id':plan['id'],'blueprint':plan['blueprint']})
    assert response.status_code==201


def test_reconnect_running_plan_does_not_schedule_again(client,setup,monkeypatch):
    calls=[]
    async def running(plan_id):
        calls.append(plan_id); db.execute("UPDATE exam_plans SET status='running' WHERE id=?",(plan_id,))
    monkeypatch.setattr(planning,'run_plan',running)
    config={**exam_config(setup),'submission_id':'stable-planning-id'}
    one=client.post('/api/exam-plans',json=config).json()
    two=client.post('/api/exam-plans',json=config).json()
    assert one['id']==two['id'] and len(calls)==1
    for _ in range(3):
        assert client.get(f"/api/exam-plans/{one['id']}").json()['status']=='running'
    assert len(calls)==1


def test_identical_concurrent_exam_submissions_create_once(client,setup,monkeypatch):
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    config={**exam_config(setup),'submission_id':'stable-exam-request'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies=list(pool.map(lambda _:client.post('/api/exams',json=config),range(2)))
    assert all(r.status_code==201 for r in replies)
    assert len({r.json()['id'] for r in replies})==1
    assert db.one('SELECT count(*) AS n FROM exams')['n']==1
    assert db.one('SELECT tokens FROM exams')['tokens']==200
    assert client.post('/api/exams',json={**config,'title':'不同设置'}).status_code==409


def test_plan_cannot_create_two_exams_even_with_different_request_ids(client,setup,monkeypatch):
    planner(monkeypatch); plan=create_plan(client,setup)
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    config={**plan['config'],'plan_id':plan['id'],'blueprint':plan['blueprint'],'submission_id':'first-request'}
    first=client.post('/api/exams',json=config).json()
    second=client.post('/api/exams',json={**config,'submission_id':'second-request'}).json()
    assert first['id']==second['id']
    assert client.get(f"/api/exam-plans/{plan['id']}").json()['exam_id']==first['id']
    assert client.put(f"/api/exam-plans/{plan['id']}/draft",json=save_body(plan)).status_code==409
    client.delete('/api/exams/'+first['id'])
    assert client.post('/api/exams',json=config).status_code==410


def test_topic_cache_reuses_rules_focus_changes_and_refreshes_only_changed_source(client,setup,monkeypatch):
    requests=[]; original=httpx.AsyncClient
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']); requests.append(task)
        assert 'materials' not in task and 'focus' not in task
        return httpx.Response(200,json=result({'topics':[{'title':'独立性'+r['id'],'objective':'理解定义并应用公式','evidence_id':r['id']+':0'} for r in task['sources']]}))
    monkeypatch.setattr(planning.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    doc=setup[1]['id']; db.execute('UPDATE documents SET page_count=2 WHERE id=?',(doc,))
    db.execute('INSERT INTO pages(document_id,number,text) VALUES (?,?,?)',(doc,2,'条件概率是已知某个事件发生时另一个事件的概率。'*4))
    config=exam_config(setup); config['ranges'][0]['end']=2
    def run(c):
        res=client.post('/api/exam-plans',json=c); return client.get('/api/exam-plans/'+res.json()['id']).json()
    first=run(config); assert first['tokens']==100
    second=run({**config,'focus':'条件概率','duration':90,'rules':[{'type':'fill','count':3,'points':4}],'parent_plan_id':first['id']})
    assert second['status']=='ready' and second['tokens']==0 and second['cache_hits']==2 and len(requests)==1
    assert len(second['blueprint'])==3
    client.put(f'/api/documents/{doc}/pages/2',json={'text':'新增内容：条件概率需要分母概率大于零。'*5})
    third=run(config)
    assert third['cache_hits']==1 and third['tokens']==100 and len(requests)==2
    assert len(requests[-1]['sources'])==1


@pytest.mark.parametrize('kind,standard,value,status',[('choice','A','A','match'),('choice','A','B','different'),('true_false','正确','正确','match'),('true_false','正确','','empty')])
def test_objective_matching_is_literal(kind,standard,value,status):
    q={'type':kind,'answer':standard,'points':5,'blanks':[]}
    checked=answer_check.check(q,AnswerCheckInput(answer=value))
    assert checked['items'][0]['status']==status


def test_fill_checks_only_listed_equivalents_and_keeps_case_signs():
    q={'type':'fill','points':10,'blanks':[{'answer':'$p$','alternatives':[]},{'answer':'1/2','alternatives':['0.5']},{'answer':'-1','alternatives':[]}]}
    checked=answer_check.check(q,AnswerCheckInput(blanks=[' p ','0.5','']))
    assert [i['status'] for i in checked['items']]==['match','match','empty']
    assert checked['suggested_score']==6.67 and not checked['all_answered']
    checked=answer_check.check(q,AnswerCheckInput(blanks=['P','0.50','1']))
    assert all(i['status']=='different' for i in checked['items'])


def test_check_endpoint_does_not_change_score_or_call_model(client,setup,monkeypatch):
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    exam=client.post('/api/exams',json=exam_config(setup)).json()
    q=client.get('/api/exams/'+exam['id']).json()['questions'][0]
    db.execute("UPDATE questions SET type='choice',answer='B' WHERE id=?",(q['id'],))
    before=db.one('SELECT tokens FROM exams WHERE id=?',(exam['id'],))['tokens']
    checked=client.post(f"/api/questions/{q['id']}/check-answer",json={'answer':'B'}).json()
    assert checked['all_match']
    assert db.one('SELECT self_score FROM questions WHERE id=?',(q['id'],))['self_score'] is None
    assert db.one('SELECT tokens FROM exams WHERE id=?',(exam['id'],))['tokens']==before


@pytest.mark.parametrize('kind,standard,answer,expected', [
    ('choice', 'A', 'A', 10), ('choice', 'A', 'B', 0),
    ('true_false', '正确', '错误', 0), ('true_false', '正确', '正确', 10),
    ('choice', 'A', '', None),
])
def test_save_answer_auto_scores_and_persists_without_model(client, setup, monkeypatch, kind, standard, answer, expected):
    monkeypatch.setattr(generation, 'generate_one', fake_generate)
    exam = client.post('/api/exams', json=exam_config(setup)).json()
    q = client.get('/api/exams/'+exam['id']).json()['questions'][0]
    db.execute('UPDATE questions SET type=?,answer=? WHERE id=?', (kind, standard, q['id']))
    before = db.one('SELECT tokens FROM exams WHERE id=?', (exam['id'],))['tokens']
    url = f"/api/questions/{q['id']}/progress"
    saved = client.patch(url, json={'user_answer': answer, 'auto_score': True})
    assert saved.status_code == 200
    assert saved.json()['self_score'] == expected
    assert saved.json()['is_wrong'] == (expected is not None and expected < 10)
    assert db.one('SELECT self_score,user_answer FROM questions WHERE id=?', (q['id'],)) == {'self_score': expected, 'user_answer': answer}
    count = len(client.get(f"/api/questions/{q['id']}/attempts").json())
    assert count == int(expected is not None)
    # Same-answer network retry must not append a second scoring record.
    client.patch(url, json={'user_answer': answer, 'auto_score': True})
    assert len(client.get(f"/api/questions/{q['id']}/attempts").json()) == count
    client.patch(url, json={'is_favorite': True})
    assert db.one('SELECT self_score FROM questions WHERE id=?', (q['id'],))['self_score'] == expected
    assert db.one('SELECT tokens FROM exams WHERE id=?', (exam['id'],))['tokens'] == before


def test_auto_fill_partial_empty_equivalents_and_manual_override(client, setup, monkeypatch):
    monkeypatch.setattr(generation, 'generate_one', fake_generate)
    exam = client.post('/api/exams', json=exam_config(setup)).json()
    q = client.get('/api/exams/'+exam['id']).json()['questions'][0]
    blanks = [{'answer':'1/2','alternatives':['0.5']}, {'answer':'p','alternatives':[]}, {'answer':'-1','alternatives':[]}]
    db.execute("UPDATE questions SET type='fill',blanks=? WHERE id=?", (db.dump(blanks), q['id']))
    url = f"/api/questions/{q['id']}/progress"
    res = client.patch(url, json={'auto_score': True, 'user_answer': db.dump(['0.5','p',''])}).json()
    assert res['self_score'] == 6.67 and res['is_wrong']
    assert res['answer_check']['items'][2]['status'] == 'empty'
    full = db.dump(['0.5','p','-1'])
    res = client.patch(url, json={'auto_score': True, 'user_answer': full}).json()
    assert res['self_score'] == 10 and not res['is_wrong']
    assert client.patch(url, json={'self_score': 8}).json()['self_score'] == 8
    assert client.patch(url, json={'auto_score': True, 'user_answer': full, 'self_score': 10}).status_code == 422
    assert client.patch(url, json={'auto_score': True, 'user_answer': '旧整段答案'}).status_code == 422
    assert db.one('SELECT self_score,user_answer FROM questions WHERE id=?', (q['id'],)) == {'self_score':8, 'user_answer':full}
    cleared = client.patch(url, json={'user_answer':'', 'self_score':None}).json()
    assert cleared['self_score'] is None and cleared['user_answer'] == ''
    blank = client.patch(url, json={'auto_score':True,'user_answer': db.dump(['','',''])}).json()
    assert blank['self_score'] is None
    assert len(client.get(f"/api/questions/{q['id']}/attempts").json()) == 3


def test_auto_score_rejects_unsupported_and_missing_answer(client, setup, monkeypatch):
    monkeypatch.setattr(generation, 'generate_one', fake_generate)
    exam = client.post('/api/exams', json=exam_config(setup)).json()
    q = client.get('/api/exams/'+exam['id']).json()['questions'][0]
    url = f"/api/questions/{q['id']}/progress"
    assert client.patch(url, json={'auto_score':True}).status_code == 422
    db.execute("UPDATE questions SET type='calculation' WHERE id=?", (q['id'],))
    assert client.patch(url, json={'auto_score':True,'user_answer':'1'}).status_code == 422
    assert client.patch(url, json={'user_answer':'1'}).json()['self_score'] is None
