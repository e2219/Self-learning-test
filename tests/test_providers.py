import asyncio
import json
import httpx
import pytest
from backend import db, deepseek, providers, ocr, planning
from tests.test_api import client, setup  # noqa: F401


def profile(**patch):
    return dict(enabled=True,name='Test',base_url='https://text.example/v1',model='text-test',api_key='text-secret',json_mode=True,**patch)


def test_role_routing_and_no_parameter_or_credential_leak(client, setup, monkeypatch):
    assert client.put('/api/settings/providers/text',json=profile()).status_code==200
    v=profile(); v.update(base_url='https://vision.example/v1',model='image-test',api_key='image-secret',json_mode=False)
    assert client.put('/api/settings/providers/vision',json=v).status_code==200
    monkeypatch.setenv('DEEPSEEK_API_KEY','legacy-env-secret')
    result=client.get('/api/settings')
    for key in ('text-secret','image-secret','legacy-env-secret'): assert key not in result.text
    seen=[]
    def handler(request):
        body=json.loads(request.content); seen.append(str(request.url))
        if request.url.host=='vision.example':
            assert body['model']=='image-test'
            assert request.headers['authorization']=='Bearer image-secret'
            assert body['messages'][0]['content'][0]['image_url']['detail']=='high'
            assert 'thinking' not in body and 'response_format' not in body
        else:
            assert body['model']=='text-test'
            assert request.headers['authorization']=='Bearer text-secret'
            assert body['response_format']=={'type':'json_object'}
        return httpx.Response(200,json={'choices':[]})
    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            body={'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA','detail':'original'}}]}], 'thinking':{'type':'disabled'}, 'response_format':{'type':'json_object'}}
            await providers.complete(transport,body,'vision')
            assert body['messages'][0]['content'][0]['image_url']['detail']=='original'
            await providers.complete(transport,{'messages':[], 'response_format':{'type':'json_object'}})
    asyncio.run(call())
    assert seen==['https://vision.example/v1/chat/completions','https://text.example/v1/chat/completions']


def test_endpoint_change_requires_new_key_and_caches_separate(client,setup):
    before=providers.identity()
    client.put('/api/settings/providers/text',json=profile())
    old=providers.identity()
    changed=profile();changed.update(base_url='https://other.example/v1',api_key='')
    assert client.put('/api/settings/providers/text',json=changed).status_code==422
    assert providers.config()['base_url']=='https://text.example/v1'
    assert before!=old
    changed['api_key']='new-secret'
    assert client.put('/api/settings/providers/text',json=changed).status_code==200
    assert providers.identity()!=old
    changed['enabled']=False
    client.put('/api/settings/providers/text',json=changed)
    assert providers.config()['builtin'] and providers.config()['api_key']=='test-key-never-send'


@pytest.mark.parametrize('url',['http://example.com/v1','https://user:password@example.com/v1','https://example.com/v1?key=secret','https://example.com/v1/chat/completions','ftp://example.com'])
def test_invalid_endpoints_do_not_echo_keys(client,setup,url):
    p=profile();p.update(base_url=url,api_key='should-not-echo')
    result=client.put('/api/settings/providers/text',json=p)
    assert result.status_code==422 and 'should-not-echo' not in result.text and 'password' not in result.text


def test_builtin_connection_check_never_sends_custom_key(client,setup,monkeypatch):
    client.put('/api/settings/providers/text',json=profile())
    original=httpx.AsyncClient
    def handler(request):
        assert request.url.host=='api.deepseek.com'
        assert request.headers['authorization']=='Bearer test-key-never-send'
        return httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    monkeypatch.setattr(deepseek.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    assert client.post('/api/settings/test-connection').status_code==200


def test_custom_connection_only_lists_models_and_hides_errors(client,setup,monkeypatch):
    client.put('/api/settings/providers/text',json=profile())
    original=httpx.AsyncClient
    def handler(request):
        assert str(request.url)=='https://text.example/v1/models' and request.method=='GET'
        assert not request.content
        return httpx.Response(401,text='text-secret')
    monkeypatch.setattr(deepseek.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    result=client.post('/api/settings/providers/text/test')
    assert result.status_code==422 and 'text-secret' not in result.text


def test_cannot_switch_provider_during_queued_work(client,setup):
    db.execute("INSERT INTO exams(id,course_id,title,config,status) VALUES (?,?,?,'{}','queued')",('running',setup[0]['id'],'running'))
    assert client.put('/api/settings/providers/text',json=profile()).status_code==409
    assert client.put('/api/settings',json={'api_key':'replace'}).status_code==409


def test_request_uses_one_endpoint_credential_snapshot(client,setup,monkeypatch):
    captured=dict(providers.config(),base_url='https://first.example/v1',api_key='first-key',model='first-model')
    calls=[]
    def config(role):
        calls.append(role)
        return captured if len(calls)==1 else dict(captured,api_key='different-service-key')
    monkeypatch.setattr(providers,'config',config)
    def handler(request):
        assert request.url.host=='first.example'
        assert request.headers['authorization']=='Bearer first-key'
        return httpx.Response(200,json={})
    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            await providers.complete(transport,{'messages':[]})
    asyncio.run(call())
    assert calls==['text']
