import asyncio
import copy
import pytest
from backend import generation, quality
from backend.answer_check import check
from backend.models import AnswerCheckInput, GeneratedQuestion, ExamInput
from tests.test_api import client, setup, exam_config, valid_payload  # noqa: F401
from tests.test_quality import blind
from tests.test_generation_recovery import result


@pytest.mark.parametrize('kind,answer,valid',[
    ('choice','A',True),('choice','AC',False),
    ('multiple_choice','A',False),('multiple_choice','C、A',True),('multiple_choice','ABCD',True),
    ('indefinite_choice','B',True),('indefinite_choice','DB',True),('indefinite_choice','',False),
    ('multiple_choice','AA',False),('indefinite_choice','AE',False),('multiple_choice','A或C',False),
])
def test_choice_contract(kind,answer,valid):
    payload={**valid_payload(),'answer':answer}
    if not valid:
        with pytest.raises(generation.OutputValidationError):
            generation.validate_content(payload,kind,[{'document_id':'doc','page':1}],[])
    else:
        q=generation.validate_content(payload,kind,[{'document_id':'doc','page':1}],[])
        assert q.answer==''.join(sorted(set(answer.replace('、',''))))


@pytest.mark.parametrize('answer,score,status',[('CA',5,'match'),('a,c',5,'match'),('A',0,'different'),('ABC',0,'different'),('BD',0,'different'),('',0,'empty')])
def test_set_scoring_without_api(answer,score,status):
    q={'type':'multiple_choice','answer':'AC','points':5,'blanks':[]}
    checked=check(q,AnswerCheckInput(answer=answer))
    assert checked['suggested_score']==score and checked['items'][0]['status']==status


@pytest.mark.parametrize('kind,correct,accepted',[
    ('choice','AC',False),('multiple_choice','AC',True),('multiple_choice','A',False),
    ('indefinite_choice','A',True),('indefinite_choice','AC',True),('indefinite_choice','AB',False)
])
def test_independent_review_checks_whole_set(kind,correct,accepted):
    q=GeneratedQuestion(**{**valid_payload(),'answer':'A' if correct=='A' else 'AC'})
    async def call(messages):
        import json
        task=json.loads(messages[-1]['content'])
        if task['stage']=='blind_review':
            payload=blind();payload['answer']=correct
            for option in payload['option_judgments']:
                option['verdict']='correct' if option['label'] in correct else 'incorrect'
        else: payload={'answer_matches':True,'explanation_consistent':True,'evidence_supported':True,'issues':[]}
        return result(payload)
    if accepted:
        assert asyncio.run(quality.review_question(call,q,kind,[],[],{}))['status']=='passed'
    else:
        with pytest.raises(quality.ReviewError): asyncio.run(quality.review_question(call,q,kind,[],[],{}))


def test_new_types_save_autoscore_and_edit(client,setup,monkeypatch):
    async def fake(q,config,refs,previous):
        return GeneratedQuestion(**{**valid_payload(),'answer':'AC','sources':[{'document_id':refs[0]['document_id'],'page':1}]}),100
    monkeypatch.setattr(generation,'generate_one',fake)
    config={**exam_config(setup),'rules':[{'type':'multiple_choice','count':1,'points':5},{'type':'indefinite_choice','count':1,'points':5}]}
    eid=client.post('/api/exams',json=config).json()['id']
    questions=client.get('/api/exams/'+eid).json()['questions']
    for q in questions:
        path='/api/questions/'+q['id']
        saved=client.patch(path+'/progress',json={'user_answer':'CA','auto_score':True})
        assert saved.status_code==200
        assert next(x for x in client.get('/api/exams/'+eid).json()['questions'] if x['id']==q['id'])['self_score']==5
        client.patch(path+'/progress',json={'user_answer':'A','auto_score':True})
        updated=next(x for x in client.get('/api/exams/'+eid).json()['questions'] if x['id']==q['id'])
        assert updated['self_score']==0 and updated['is_wrong']
        client.patch(path+'/progress',json={'user_answer':'','auto_score':True})
        assert next(x for x in client.get('/api/exams/'+eid).json()['questions'] if x['id']==q['id'])['self_score'] is None
        edit={**q,'answer':'B'}
        response=client.put(path,json=edit)
        assert response.status_code==(422 if q['type']=='multiple_choice' else 200)
    # Seven rules are accepted without changing the 30-question total limit.
    config['rules']=[{'type':t,'count':1,'points':5} for t in generation.TYPE_NAMES]
    assert len(ExamInput.model_validate(config).rules)==7
