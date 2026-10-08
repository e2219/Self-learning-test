"""No paid API calls: exercise image transport, caching and recovery boundaries."""
import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from backend import db, ocr, generation, planning, quality, usage
from backend.models import GeneratedQuestion
from tests.test_api import client, setup, exam_config, valid_payload  # noqa: F401
from tests.test_ocr import blank_doc, response_body, TEXT
from tests.test_cost_reference_images import transport
from tests.test_generation_recovery import result
from tests.test_quality import blind


def png(color='white'):
    f=io.BytesIO(); Image.new('RGB',(200,100),color).save(f,format='PNG'); return f.getvalue()


def post_job(client,doc,**extra):
    response=client.post(f"/api/documents/{doc['id']}/ocr",json={'start':1,'end':1,**extra})
    assert response.status_code==201,response.text
    return client.get('/api/ocr/'+response.json()['id']).json()


def test_real_ocr_adapter_deduplicates_across_documents_and_honors_force(client,setup,monkeypatch):
    calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        assert body['thinking']=={'type':'disabled'}
        assert body['messages'][0]['content'][1]['image_url']['detail']=='original'
        data=response_body(TEXT,model='actual-flash')
        data['usage']={'prompt_tokens':800,'completion_tokens':200,'total_tokens':1000,'prompt_cache_hit_tokens':100,'completion_tokens_details':{'reasoning_tokens':0}}
        return httpx.Response(200,json=data)
    transport(monkeypatch,handler)
    d1=blank_doc(client,setup[0],1);d2=blank_doc(client,setup[0],1)
    first=post_job(client,d1,submission_id='same-request-key')
    again=post_job(client,d1,submission_id='same-request-key')
    assert first['id']==again['id'] and len(calls)==1
    assert first['usage'][0]['models']=='actual-flash'
    assert first['usage'][0]['reasoning_tokens']==0
    second=post_job(client,d2)
    assert second['tokens']==0 and second['pages'][0]['stage']=='cached' and len(calls)==1
    assert client.get(f"/api/documents/{d2['id']}/pages/1").json()['text']==TEXT
    post_job(client,d2,force=True)
    assert len(calls)==2
    assert client.post(f"/api/documents/{d1['id']}/ocr",json={'start':1,'end':1,'force':True,'submission_id':'same-request-key'}).status_code==409
    client.put(f"/api/documents/{d1['id']}/pages/1",json={'text':'人工版本'})
    post_job(client,d1,force=True)
    assert len(calls)==2


def test_ocr_cache_separates_configuration_and_different_images(client,setup,monkeypatch):
    first=ocr.cache_key(png())
    assert first!=ocr.cache_key(png('black'))
    monkeypatch.setattr(ocr,'CACHE_VERSION','new-recognition-rules')
    assert first!=ocr.cache_key(png())


def test_ocr_budget_only_resumes_remaining_pages_and_records_failed_usage(client,setup,monkeypatch):
    doc=blank_doc(client,setup[0],2);calls=[]
    monkeypatch.setattr(ocr,'render_page',lambda path,n:png('white' if n==1 else 'black'))
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json=response_body(TEXT))
    transport(monkeypatch,handler)
    job=post_job(client,doc,end=2,token_budget=1)
    assert job['status']=='partial' and len(calls)==1 and job['tokens']==789
    assert client.put('/api/ocr/'+job['id']+'/budget',json={'token_budget':5000}).status_code==200
    client.post('/api/ocr/'+job['id']+'/retry')
    resumed=client.get('/api/ocr/'+job['id']).json()
    assert resumed['status']=='ready' and resumed['tokens']==1578 and len(calls)==2
    assert [r['calls'] for r in resumed['usage']]==[1,1]


def vision_handler(doc, calls):
    def handler(req):
        body=json.loads(req.content)
        blocks=body['messages'][-1]['content']
        task=json.loads(blocks[0]['text'] if isinstance(blocks,list) else blocks)
        stage=task.get('stage','generation');calls.append((stage,body))
        if stage=='blind_review': payload=blind()
        elif stage=='consistency_review': payload={'answer_matches':True,'explanation_consistent':True,'evidence_supported':True,'issues':[]}
        elif stage=='combined_review': payload={**blind(),'answer_matches':True,'explanation_consistent':True}
        else:
            payload=valid_payload();payload['sources']=[{'document_id':doc['id'],'page':1}]
        data=result(payload);data['model']='actual-vision' if isinstance(blocks,list) else 'actual-text'
        return httpx.Response(200,json=data)
    return handler


def test_direct_vision_no_transcription_local_plan_idempotency_and_budget_resume(client,setup,monkeypatch):
    doc=blank_doc(client,setup[0],1);calls=[]
    transport(monkeypatch,vision_handler(doc,calls))
    config={**exam_config((setup[0],doc),1),'reading_mode':'vision','token_budget':50,
        'rules':[{'type':'choice','count':1,'points':5}],'instructions':'模仿原图考点，不照抄原题','submission_id':'vision-plan-key'}
    pid=client.post('/api/exam-plans',json=config).json()['id']
    plan=client.get('/api/exam-plans/'+pid).json()
    assert plan['status']=='ready' and plan['tokens']==0 and not calls
    assert client.post('/api/exam-plans',json=config).json()['id']==pid
    payload={**config,'submission_id':'vision-exam-key','plan_id':pid,'blueprint':plan['blueprint']}
    response=client.post('/api/exams',json=payload)
    assert response.status_code==201,response.text
    eid=response.json()['id'];exam=client.get('/api/exams/'+eid).json()
    assert exam['status']=='paused' and exam['tokens']==100 and len(calls)==1
    assert client.post('/api/exams',json=payload).json()['id']==eid and len(calls)==1
    client.put('/api/exams/'+eid+'/budget',json={'token_budget':2000,'max_attempts':1})
    client.post('/api/exams/'+eid+'/retry')
    exam=client.get('/api/exams/'+eid).json()
    assert exam['status']=='ready' and exam['tokens']==300,exam
    assert [s for s,_ in calls]==['generation','blind_review','consistency_review']
    assert all(b['model']=='deepseek-flash' for _,b in calls)
    for _,body in calls:
        blocks=body['messages'][-1]['content']
        assert sum(b['type']=='image_url' for b in blocks)==1
        assert blocks[-1]['image_url']['detail']=='original'
    assert client.get(f"/api/documents/{doc['id']}/pages/1").json()['text']==''
    assert exam['questions'][0]['review']['source_images_checked']
    assert 'data:image' not in db.one('SELECT config FROM exams WHERE id=?',(eid,))['config']
    assert 'source_image_review' in [r['stage'] for r in exam['usage']]


def test_vision_scope_and_mode_constraints(client,setup):
    doc=blank_doc(client,setup[0],5)
    cfg={**exam_config((setup[0],doc)), 'reading_mode':'vision'}
    cfg['ranges'][0]['end']=5
    assert client.post('/api/exam-plans',json=cfg).status_code==422
    cfg['ranges'][0]['end']=1
    assert client.post('/api/exam-plans',json={**cfg,'mode':'reference'}).status_code==422
    assert client.post('/api/exams',json={**cfg,'batch_generation':True}).status_code==422
    cfg['course_id']=client.post('/api/courses',json={'name':'别的课程'}).json()['id']
    assert client.post('/api/retrieval-preview',json=cfg).status_code==422


@pytest.mark.parametrize('uncertain',[True,False])
def test_text_with_ocr_evidence_rechecks_original_and_never_uses_combined_review(client,setup,monkeypatch,uncertain):
    doc=setup[1];calls=[]
    db.execute('UPDATE pages SET ocr_done=1 WHERE document_id=?',(doc['id'],))
    if uncertain:
        db.execute("UPDATE pages SET text=text || '\n[图形未转写]' WHERE document_id=?",(doc['id'],))
    transport(monkeypatch,vision_handler(doc,calls))
    cfg={**exam_config(setup,1),'review_mode':'adaptive','rules':[{'type':'choice','count':1,'points':5}]}
    eid=client.post('/api/exams',json=cfg).json()['id']
    exam=client.get('/api/exams/'+eid).json()
    assert exam['status']=='ready',exam
    assert [s for s,_ in calls]==['generation','blind_review','consistency_review']
    assert [isinstance(b['messages'][-1]['content'],list) for _,b in calls]==[False,uncertain,False]


def test_simple_text_adaptive_review_saves_one_call_and_is_labelled(client,setup,monkeypatch):
    calls=[];transport(monkeypatch,vision_handler(setup[1],calls))
    cfg={**exam_config(setup,1),'review_mode':'adaptive','rules':[{'type':'choice','count':1,'points':5}]}
    eid=client.post('/api/exams',json=cfg).json()['id']
    exam=client.get('/api/exams/'+eid).json()
    assert exam['status']=='ready',exam
    assert [s for s,_ in calls]==['generation','combined_review']
    assert exam['questions'][0]['review']['method']=='combined'
    assert exam['tokens']==200


def test_combined_review_rejects_explanation_mismatch():
    async def call(messages):
        return result({**blind(),'answer_matches':True,'explanation_consistent':False})
    with pytest.raises(quality.ReviewError):
        asyncio.run(quality.review_question(call,GeneratedQuestion(**valid_payload()),'choice',[],[],{'review_mode':'adaptive'}))


def test_usage_keeps_unknown_distinct_from_zero_and_no_raw_text(client,setup):
    usage.record('ocr','test','ocr_page:1',{'model':'actual','usage':{'total_tokens':100,'completion_tokens_details':{'reasoning_tokens':True}}})
    row=usage.summary('ocr','test')[0]
    assert row['reasoning_tokens'] is None and row['input_tokens'] is None and row['incomplete_calls']==1
    assert row['models']=='actual'


def test_reference_structure_preserves_only_source_conditions(client,setup):
    ref={'id':'0','document_id':setup[1]['id'],'page':1,'name':'卷','kind':'往年试卷','role':'reference','text':'单选题（5 分）：设 P(A)=0.5，求补事件概率。'}
    item={'title':'补事件','objective':'求补事件概率','evidence_id':'0:0','question_type':'choice','original_points':5,'question_style':'求概率','key_conditions':['P(A)=0.5']}
    topic=planning.validate_topics({'topics':[item]},[ref],'')[0]
    assert topic['reference_structure'][0]['original_points']==5
    item['key_conditions']=['P(A)=0.9']
    with pytest.raises(generation.GenerationError): planning.validate_topics({'topics':[item]},[ref],'')
