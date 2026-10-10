"""No live requests: verify metering, focus selection and paid-stage recovery."""
import asyncio
import json
import httpx
import pytest
from backend import db, usage, providers, generation, planning
from tests.test_api import client, setup, exam_config, valid_payload
from tests.review_fixtures import review_response
from tests.test_generation_recovery import result


def call(handler, body=None, role='text', owner='diagnostic'):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            return await usage.request(transport, body or {'messages':[]}, role,
                owner_type='exam', owner_id=owner, stage='generation')
    return asyncio.run(run())


def test_ledger_snapshots_prices_modes_and_never_discloses_keys(client, setup):
    seen=[]
    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, headers={'x-request-id':'trace-123'}, json={
            'model':'deepseek-flash', 'usage':{'prompt_tokens':1000,'completion_tokens':200,
            'total_tokens':1200,'prompt_cache_hit_tokens':100,'completion_tokens_details':{'reasoning_tokens':50}},
            'choices':[{'finish_reason':'stop'}]})
    response=call(handler)
    usage.finish(usage.decode(response),'validated')
    assert seen[0]['thinking']=={'type':'disabled'}
    ledger=client.get('/api/usage').json()
    row=ledger['rows'][0]
    assert row['total_tokens']==1200 and row['reasoning_tokens']==50
    assert row['estimated_usd_min']==pytest.approx((900*.15+100*.003+200*.6)/1e6)
    assert row['estimated_usd_max']==pytest.approx(row['estimated_usd_min']*2)
    recent=ledger['recent'][0]
    assert recent['requested_model']=='deepseek-chat' and recent['model']=='deepseek-flash'
    assert recent['request_id']=='trace-123' and recent['outcome']=='validated'
    assert 'test-key-never-send' not in json.dumps(ledger)
    before=row['estimated_usd_min']
    db.set_setting('model','deepseek-reasoner')
    call(handler)
    assert seen[-1]['thinking']=={'type':'enabled'}
    assert db.one('SELECT estimated_usd_min FROM usage_events WHERE id=1')['estimated_usd_min']==before
    call(handler,role='vision')
    assert seen[-1]['thinking']=={'type':'enabled'}
    call(handler,{'messages':[],'thinking':{'type':'disabled'}},'vision')
    assert seen[-1]['thinking']=={'type':'disabled'}


@pytest.mark.parametrize('mode,outcome', [('timeout','timeout'),('bad_json','invalid_json'),('http','http_error')])
def test_failed_requests_keep_unknown_usage_and_safe_diagnostics(client,setup,mode,outcome):
    def handler(req):
        if mode=='timeout': raise httpx.ReadTimeout('PRIVATE API KEY',request=req)
        return httpx.Response(401 if mode=='http' else 200, text='PRIVATE API KEY')
    if mode=='timeout':
        with pytest.raises(httpx.ReadTimeout): call(handler)
    else: call(handler)
    data=client.get('/api/usage').json()
    recent=data['recent'][0]
    # A non-JSON error body must not hide the HTTP failure status.
    assert recent['outcome']==outcome
    assert recent['total_tokens'] is None
    assert data['rows'][0]['unpriced_calls']==1
    assert 'PRIVATE' not in json.dumps(data)


def test_legacy_usage_not_backdated_and_dates_validated(client,setup):
    db.execute("INSERT INTO usage_events(owner_type,owner_id,stage,attempt,model,total_tokens) VALUES ('exam','deleted','generation',1,'',42)")
    db.init_db()
    data=client.get('/api/usage').json()
    assert data['undated_calls']==1 and data['recent'][0]['created_at'] is None
    assert data['rows'][0]['estimated_usd_min'] is None
    assert client.get('/api/usage?start=2026-01-01').json()['rows']==[]
    for query in ('start=bad','start=2026-13-01','start=2026-10-10&end=2026-01-01'):
        assert client.get('/api/usage?'+query).status_code==422
    client.post('/api/logout')
    assert client.get('/api/usage').status_code==401


def test_custom_prices_openai_cache_and_default_thinking(client,setup):
    profile=dict(enabled=True,name='demo',base_url='https://example.test/v1',model='m',api_key='secret',
        input_price=1,cached_price=.1,output_price=2)
    assert client.put('/api/settings/providers/text',json=profile).status_code==200
    def handler(req):
        assert 'thinking' not in json.loads(req.content)
        return httpx.Response(200,json={'model':'m','usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110,'prompt_tokens_details':{'cached_tokens':20}}})
    call(handler)
    row=usage.ledger()['rows'][0]
    assert row['estimated_usd_min']==pytest.approx(.000102)
    assert row['estimated_usd_min']==row['estimated_usd_max']
    profile['input_price']=2
    client.put('/api/settings/providers/text',json=profile)
    assert usage.ledger()['rows'][0]['estimated_usd_min']==row['estimated_usd_min']
    profile['cached_price']=None
    assert client.put('/api/settings/providers/text',json=profile).status_code==422


def test_focus_is_not_inherited_from_whole_page_quote():
    ref=dict(kind='教材',text='数学期望和分布函数都出现在这张表格。',document_id='d',page=1,name='sample')
    common=dict(sources=[{'quote':ref['text']}])
    expectation=planning.ranked_topic(dict(common,title='数学期望',objective='计算数学期望'),ref,'数学期望')
    distribution=planning.ranked_topic(dict(common,title='分布函数',objective='计算分布函数'),ref,'数学期望')
    assert expectation['weight']==4 and distribution['weight']==1
    assert '匹配指定重点' not in distribution['reasons']


def test_resume_after_consistency_timeout_reuses_passed_blind_review(client,setup,monkeypatch):
    config=exam_config(setup,count=1)
    config['rules']=[{'type':'choice','count':1,'points':5}]
    config['review_mode']='full'
    calls=[]
    fail=[True]
    original=httpx.AsyncClient
    def handler(req):
        body=json.loads(req.content)
        task=json.loads(body['messages'][1]['content'])
        stage=task.get('stage','generation'); calls.append(stage)
        if stage=='consistency_review' and fail[0]:
            raise httpx.ReadTimeout('simulated',request=req)
        review=review_response(req)
        if review:
            data=review.json();data['usage']={'total_tokens':20}
            return httpx.Response(200,json=data)
        payload=valid_payload();payload['sources']=[{'document_id':setup[1]['id'],'page':1}]
        return httpx.Response(200,json=result(payload,100))
    monkeypatch.setattr(generation.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    res=client.post('/api/exams',json=config)
    assert res.status_code==201,res.text
    exam_id=res.json()['id']
    exam=client.get(f'/api/exams/{exam_id}').json()
    assert exam['status']=='partial' and exam['tokens']==120
    assert calls==['generation','blind_review','consistency_review']
    assert len(db.rows('SELECT * FROM review_checkpoints'))==1
    fail[0]=False
    client.post(f'/api/exams/{exam_id}/retry')
    after=client.get(f'/api/exams/{exam_id}').json()
    assert after['status']=='ready',after
    assert calls==['generation','blind_review','consistency_review','consistency_review']
    assert after['tokens']==140 and usage.spent('exam',exam_id)==140
    assert next(r for r in usage.summary('exam',exam_id) if r['stage']=='consistency_review')['retry_calls']==1
    # Deleting the question via its exam removes checkpoints, not billing history.
    assert client.delete(f'/api/exams/{exam_id}').status_code==200
    assert db.rows('SELECT * FROM review_checkpoints')==[]
    assert len(usage.ledger()['recent'])==4


def test_planning_budget_keeps_cache_and_resumes_remaining_material(client,setup,monkeypatch):
    from tests.test_api import sample_pdf
    course,doc=setup
    doc2=client.post(f"/api/courses/{course['id']}/documents", files={'file':('second.pdf',sample_pdf(),'application/pdf')}).json()
    client.put(f"/api/documents/{doc2['id']}/pages/1",json={'text':'条件概率的乘法公式与计算方法。'*15})
    monkeypatch.setattr(planning,'BATCH_CHARS',1)
    original=httpx.AsyncClient
    calls=[]
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']);calls.append(task)
        ev=task['evidence'][0]['id']
        return httpx.Response(200,json=result({'topics':[{'title':'独立性' if len(calls)==1 else '条件概率',
            'objective':'计算联合概率','evidence_id':ev}]},100))
    monkeypatch.setattr(planning.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    config=exam_config(setup)
    config['ranges'].append({'document_id':doc2['id'],'start':1,'end':1})
    config['planning_token_budget']=100
    plan_id=client.post('/api/exam-plans',json=config).json()['id']
    plan=client.get('/api/exam-plans/'+plan_id).json()
    assert plan['status']=='failed' and 'PLAN_BUDGET' in plan['error']
    assert len(calls)==1 and len(db.rows('SELECT * FROM topic_cache'))==1
    config['planning_token_budget']=200
    plan_id=client.post('/api/exam-plans',json=config).json()['id']
    plan=client.get('/api/exam-plans/'+plan_id).json()
    assert plan['status']=='ready' and plan['cache_hits']==1
    assert len(calls)==2 and plan['tokens']==100


def test_review_checkpoint_requires_exact_request_sources_and_provider(client,setup,monkeypatch):
    from backend import review_cache
    from tests.test_api import fake_generate
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    exam_id=client.post('/api/exams',json=exam_config(setup,1)).json()['id']
    question=db.one('SELECT id FROM questions WHERE exam_id=?',(exam_id,))['id']
    messages=[{'role':'user','content':'candidate A'}];context={'source':'v1'}
    response={'usage':{'total_tokens':100},'choices':[]}
    review_cache.save(question,'blind_review',messages,context,response)
    assert review_cache.get(question,'blind_review',messages,context)==response
    assert review_cache.get(question,'blind_review',[{'role':'user','content':'candidate B'}],context) is None
    assert review_cache.get(question,'blind_review',messages,{'source':'v2'}) is None
    db.set_setting('vision_thinking','disabled')
    assert review_cache.get(question,'blind_review',messages,context) is None
    db.set_setting('vision_thinking','enabled')
    assert review_cache.get(question,'blind_review',messages,context)==response
    client.post(f'/api/questions/{question}/regenerate')
    assert db.rows('SELECT * FROM review_checkpoints')==[]


def test_interrupted_requests_are_not_reported_as_free(client,setup):
    usage.start('exam','gone','generation')
    db.init_db()
    row=usage.ledger()['recent'][0]
    assert row['outcome']=='interrupted' and row['total_tokens'] is None
    assert usage.ledger()['rows'][0]['unpriced_calls']==1


def test_error_response_usage_is_in_exam_counter_and_ledger(client,setup,monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(generation.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(
        lambda req:httpx.Response(429,json={'usage':{'total_tokens':73}})),**kw))
    exam_id=client.post('/api/exams',json=exam_config(setup,1)).json()['id']
    exam=client.get(f'/api/exams/{exam_id}').json()
    assert exam['status']=='partial' and exam['tokens']==73
    assert usage.spent('exam',exam_id)==73
    assert usage.ledger()['recent'][0]['outcome']=='http_error'
