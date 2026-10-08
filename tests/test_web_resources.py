import json
import pytest
from backend import db, web_resources
from tests.test_api import client, setup  # noqa: F401


@pytest.fixture
def source(client,setup,monkeypatch):
    async def response(site,params):
        if params['action']=='parse': return {'parse':{'text':'<p>求两个独立事件同时发生的概率。</p><p>答案：概率相乘。</p>'}}
        return {'query':{'rightsinfo':{'url':'https://creativecommons.org/licenses/by-sa/4.0/deed.zh'},'pages':[{'pageid':10,'ns':0,'title':'概率练习','revisions':[{'revid':123,'slots':{'main':{'content':'求两个独立事件同时发生的概率。'}}}]}]}}
    monkeypatch.setattr(web_resources,'request',response)
    return client.get('/api/web-resources/preview?site=zh&page_id=10').json()


def payload(setup,source):
    return dict(source_id=source['id'],course_id=setup[0]['id'],title='来源摘录测试',question_type='calculation',confirmed_license=True,submission_id='import-test-123',question=dict(stem='求两个独立事件同时发生的概率。',options=[],answer='概率相乘',explanation='独立事件概率相乘。',knowledge='独立事件',sources=[{'document_id':'fake','page':1}],points=5))


def test_import_without_ai_preserves_attribution_idempotency_and_edit(client,setup,source,monkeypatch):
    assert source['importable'] and source['revision']==123
    monkeypatch.setattr('backend.providers.complete',lambda *a,**kw: pytest.fail('Must not call models'))
    request=payload(setup,source)
    result=client.post('/api/web-resources/import',json=request)
    assert result.status_code==201,result.text
    exam=result.json();q=exam['questions'][0]
    assert exam['tokens']==0 and exam['status']=='ready'
    assert q['sources'][0]['url']=='https://zh.wikiversity.org/w/index.php?oldid=123'
    assert q['sources'][0]['license']=='CC BY-SA 4.0'
    assert q['review']['method']=='web_import'
    assert client.post('/api/web-resources/import',json=request).json()['id']==exam['id']
    changed=dict(q,stem='求三个独立事件同时发生的概率。')
    changed['sources']=[{'document_id':'web:'+source['id'],'page':1}]
    edited=client.put('/api/questions/'+q['id'],json=changed)
    assert edited.status_code==200,edited.text
    assert edited.json()['sources'][0]['license']=='CC BY-SA 4.0' and edited.json()['sources'][0]['modified']
    assert client.post('/api/questions/'+q['id']+'/regenerate').status_code==422
    assert client.post('/api/questions/'+q['id']+'/explanation').status_code==422
    assert client.post('/api/exams/'+exam['id']+'/retry').status_code==422
    assert client.delete('/api/exams/'+exam['id']).status_code==200
    assert client.post('/api/web-resources/import',json=request).status_code==410


def test_import_rejects_unverified_license_or_unrelated_content(client,setup,source):
    p=payload(setup,source);p['confirmed_license']=False
    assert client.post('/api/web-resources/import',json=p).status_code==422
    p['confirmed_license']=True;p['question']['stem']='不属于此来源的另一道题目。'
    assert client.post('/api/web-resources/import',json=p).status_code==422
    p=payload(setup,source)
    source['importable']=False
    db.execute('UPDATE web_sources SET data=? WHERE id=?',(db.dump(source),source['id']))
    assert client.post('/api/web-resources/import',json=p).status_code==422


@pytest.mark.parametrize('license_url,body',[
    ('https://example.com/unknown','<p>普通文字</p>'),
    ('https://creativecommons.org/licenses/by-sa/4.0/','<p>All rights reserved</p>'),
    ('https://creativecommons.org/licenses/by-sa/4.0/','<img src="third-party.png"><p>普通文字</p>'),
    ('https://creativecommons.org/licenses/by-sa/4.0/','<blockquote>他人引文</blockquote>')])
def test_ambiguous_pages_are_link_only(client,setup,monkeypatch,license_url,body):
    async def response(site,params):
        if params['action']=='parse': return {'parse':{'text':body}}
        return {'query':{'rightsinfo':{'url':license_url},'pages':[{'ns':0,'title':'测试','revisions':[{'revid':1,'slots':{'main':{'content':''}}}]}]}}
    monkeypatch.setattr(web_resources,'request',response)
    result=client.get('/api/web-resources/preview?site=en&page_id=1')
    assert result.status_code==200 and not result.json()['importable']


def test_search_uses_allowlist_and_strips_html(client,setup,monkeypatch):
    async def response(site,params):
        assert site=='en' and params['srnamespace']==0
        return {'query':{'search':[{'pageid':1,'title':'Probability','snippet':'<span>probability</span><script>bad()</script>'}]}}
    monkeypatch.setattr(web_resources,'request',response)
    result=client.get('/api/web-resources/search?site=en&q=probability')
    assert result.json()[0]['snippet']=='probability'
    assert result.json()[0]['url']=='https://en.wikiversity.org/wiki/Probability'
    assert client.get('/api/web-resources/search?site=http://127.0.0.1&q=x').status_code==422
    client.post('/api/logout')
    assert client.get('/api/web-resources/search?site=en&q=x').status_code==401


def test_append_to_same_imported_exam_is_idempotent(client,setup,source):
    p=payload(setup,source)
    first=client.post('/api/web-resources/import',json=p).json()
    p['target_exam_id']=first['id'];p['submission_id']='append-test-123'
    result=client.post('/api/web-resources/import',json=p)
    assert result.status_code==201,result.text
    assert [q['position'] for q in result.json()['questions']]==[1,2]
    assert len(client.post('/api/web-resources/import',json=p).json()['questions'])==2
