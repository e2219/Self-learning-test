import asyncio
import copy
import io
import json
from collections import Counter

import httpx
import pytest
from PIL import Image

from backend import db, generation, ocr, planning, usage, explanations
from tests.test_api import client, setup, exam_config, valid_payload, fake_generate  # noqa: F401
from tests.test_quality import blind
from tests.test_generation_recovery import result


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize('fmt,name', [('PNG','page.png'),('JPEG','photo.jpg'),('WEBP','sheet.webp')])
def test_image_import_to_ocr_and_retrieval(client, setup, monkeypatch, fmt, name):
    output=io.BytesIO()
    Image.new('RGB',(200,300),'white').save(output,format=fmt)
    response=client.post(f"/api/courses/{setup[0]['id']}/documents", files={'file':(name,output.getvalue())}, data={'kind':'往年试卷'})
    assert response.status_code==201
    doc=response.json()
    assert doc['page_count']==1 and doc['kind']=='往年试卷'
    assert client.get(f"/api/documents/{doc['id']}/file").content.startswith(b'%PDF')
    async def recognize(image):
        assert image.startswith(b'\xff\xd8')
        return ocr.OCRResult(text='选择题：设事件 A 与 B 相互独立，已知 P(A)=0.5，P(B)=0.4，请判断联合概率是否为 0.2，并给出依据。'),80
    monkeypatch.setattr(ocr,'recognize_page',recognize)
    job=client.post(f"/api/documents/{doc['id']}/ocr",json={'start':1,'end':1}).json()
    assert client.get('/api/ocr/'+job['id']).json()['tokens']==80
    assert generation.material_candidates({**exam_config(setup),'ranges':[{'document_id':doc['id'],'start':1,'end':1}]})[0][0]['role']=='reference'


def test_invalid_image_leaves_no_upload(client, setup):
    before=list((db.DATA_DIR/'uploads').iterdir())
    response=client.post(f"/api/courses/{setup[0]['id']}/documents",files={'file':('bad.png',b'not an image')})
    assert response.status_code==422
    assert list((db.DATA_DIR/'uploads').iterdir())==before


def test_reference_mode_instructions_distribution_and_cache(client, setup, monkeypatch):
    calls=[]
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']); calls.append(task)
        assert task['custom_instructions']=='模仿往年卷，只改变数字'
        assert task['sources'][0]['role']=='reference'
        assert 'title' in task['schema']['$defs']['TopicDraft']['properties']
        return httpx.Response(200,json=result({'topics':[
            {'title':'事件独立性','objective':'辨析独立性','question_type':'choice','occurrences':3,'evidence_id':'0:0'},
            {'title':'联合概率','objective':'计算联合概率','question_type':'calculation','occurrences':1,'evidence_id':'0:0'}]}))
    transport(monkeypatch,handler)
    config={**exam_config(setup),'mode':'reference','random_count':4,'instructions':'模仿往年卷，只改变数字'}
    config['ranges'][0]['role']='reference'
    config['rules']=[{'type':'choice','count':1,'points':5},{'type':'calculation','count':1,'points':10}]
    plan_id=client.post('/api/exam-plans',json=config).json()['id']
    plan=client.get('/api/exam-plans/'+plan_id).json()
    assert plan['status']=='ready',plan
    assert Counter(s['type'] for s in plan['blueprint'])=={'choice':3,'calculation':1}
    assert plan['usage'][0]['stage']=='planning'
    second=client.post('/api/exam-plans',json=config).json()['id']
    assert client.get('/api/exam-plans/'+second).json()['cache_hits']>0
    assert len(calls)==1
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    exam=client.post('/api/exams',json={**config,'plan_id':plan_id,'blueprint':plan['blueprint']})
    assert exam.status_code==201,exam.json()
    changed={**config,'instructions':'换一种命题要求'}
    assert planning.cache_key({}, {'text':'x','kind':'教材'},config['instructions'])!=planning.cache_key({}, {'text':'x','kind':'教材'},changed['instructions'])
    config['ranges'][0]['role']='knowledge'
    assert client.post('/api/exam-plans',json=config).status_code==422


def test_usage_budget_pause_resume_reuses_candidate(client, setup, monkeypatch):
    stages=[]
    doc=setup[1]['id']
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content'])
        stage=task.get('stage','generation');stages.append(stage)
        if stage=='blind_review': payload=blind()
        elif stage=='consistency_review': payload={'answer_matches':True,'explanation_consistent':True,'evidence_supported':True,'issues':[]}
        else:
            assert task['custom_instructions']=='保持概念辨析'
            payload=valid_payload();payload['sources']=[{'document_id':doc,'page':1}]
        data=result(payload);data['usage']={'total_tokens':100,'prompt_tokens':70,'completion_tokens':30,'prompt_cache_hit_tokens':20}
        return httpx.Response(200,json=data)
    transport(monkeypatch,handler)
    config={**exam_config(setup),'instructions':'保持概念辨析','token_budget':50,'rules':[{'type':'choice','count':1,'points':5}]}
    exam_id=client.post('/api/exams',json=config).json()['id']
    exam=client.get('/api/exams/'+exam_id).json()
    assert exam['status']=='paused' and exam['tokens']==100
    assert stages==['generation']
    assert exam['usage'][0]['input_tokens']==70 and exam['usage'][0]['cached_tokens']==20
    assert client.post('/api/exams/'+exam_id+'/retry').status_code==422
    assert client.put('/api/exams/'+exam_id+'/budget',json={'token_budget':1000,'max_attempts':1}).status_code==200
    client.post('/api/exams/'+exam_id+'/retry')
    exam=client.get('/api/exams/'+exam_id).json()
    assert exam['status']=='ready' and exam['tokens']==300,exam
    assert stages==['generation','blind_review','consistency_review']


@pytest.mark.parametrize('budget', [0, 50])
def test_pair_generation_counts_shared_request_and_individual_reviews(client,setup,monkeypatch,budget):
    refs=generation.retrieve(exam_config(setup))
    monkeypatch.setattr(planning,'planned_references',lambda config,pos:(refs,{'title':'独立性','objective':f'角度{pos}'}))
    calls=[]
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']);calls.append(task)
        if 'tasks' in task:
            questions=[]
            for target in task['tasks']:
                q=valid_payload();q['stem']+=str(target['task']['position']);q['sources']=[{'document_id':refs[0]['document_id'],'page':1}]
                questions.append({'position':target['task']['position'],'question':q})
            payload={'questions':questions}
        elif task['stage']=='blind_review':payload=blind()
        else:payload={'answer_matches':True,'explanation_consistent':True,'evidence_supported':True,'issues':[]}
        return httpx.Response(200,json=result(payload))
    transport(monkeypatch,handler)
    config={**exam_config(setup),'batch_generation':True,'token_budget':budget,'rules':[{'type':'choice','count':2,'points':5}]}
    eid=client.post('/api/exams',json=config).json()['id']
    exam=client.get('/api/exams/'+eid).json()
    if budget:
        assert exam['status']=='paused' and exam['tokens']==100
        client.put('/api/exams/'+eid+'/budget',json={'token_budget':1000,'max_attempts':2})
        client.post('/api/exams/'+eid+'/retry')
        exam=client.get('/api/exams/'+eid).json()
    assert exam['status']=='ready',exam
    assert len(calls)==5 and exam['tokens']==500
    assert [r for r in exam['usage'] if r['stage']=='generation_batch'][0]['calls']==1


def test_expansion_is_cached_and_keeps_original_when_review_fails(client, setup, monkeypatch):
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    eid=client.post('/api/exams',json=exam_config(setup)).json()['id']
    q=client.get('/api/exams/'+eid).json()['questions'][0]
    calls=[]
    reject=[False]
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']);calls.append(task)
        if 'schema' in task:payload={'answer_matches':True,'explanation_consistent':not reject[0],'evidence_supported':True,'issues':[]}
        else:payload={'explanation':'逐步运用独立事件乘法公式，计算得到参考答案。'}
        return httpx.Response(200,json=result(payload))
    transport(monkeypatch,handler)
    response=client.post('/api/questions/'+q['id']+'/explanation')
    assert response.status_code==200,response.json()
    assert response.json()['answer']==q['answer']
    assert response.json()['review']['expanded_explanation']
    client.post('/api/questions/'+q['id']+'/explanation')
    assert len(calls)==2
    reject[0]=True
    other=client.get('/api/exams/'+eid).json()['questions'][1]
    before_tokens=client.get('/api/exams/'+eid).json()['tokens']
    assert client.post('/api/questions/'+other['id']+'/explanation').status_code==422
    after=client.get('/api/exams/'+eid).json()
    assert after['questions'][1]['explanation']==other['explanation']
    assert after['tokens']==before_tokens+200
    assert eid not in generation.active_exams
    assert usage.compact_schema({'properties':{'title':{'type':'string','title':'Name'}}})=={'properties':{'title':{'type':'string'}}}


@pytest.mark.parametrize('attempts',[1,2,3])
def test_retry_limit_and_failed_usage(client,setup,monkeypatch,attempts):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json=result({}))
    transport(monkeypatch,handler)
    with pytest.raises(generation.GenerationError) as error:
        asyncio.run(generation.generate_one({'type':'choice','points':5},{'difficulty':'基础巩固','max_attempts':attempts},[],[]))
    assert len(calls)==attempts and error.value.tokens==attempts*100
