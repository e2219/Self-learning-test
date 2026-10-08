import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend.library import store
from backend.library.main import app


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA_DIR', tmp_path/'library')
    monkeypatch.setenv('LIBRARY_COOKIE_SECURE', 'false')
    monkeypatch.delenv('LIBRARY_PUBLIC_ORIGIN', raising=False)
    monkeypatch.delenv('LIBRARY_REGISTRATION_CODE', raising=False)
    with TestClient(app) as client:
        yield client


def account(client, username):
    client.cookies.clear()
    credentials = {'username':username, 'password':'safe-test-password'}
    assert client.post('/api/register', json={**credentials,'nickname':username}).status_code == 201
    response = client.post('/api/login', json=credentials)
    assert response.status_code == 200
    return response.json(), client.cookies.get('zhixi_library_session')


def use(client, cookie):
    client.cookies.clear()
    client.cookies.set('zhixi_library_session', cookie)


def pack():
    return {'format':'zhixi-study-pack','version':1,'kind':'exam','title':'概率论练习','course':'概率论',
        'questions':[{'type':'choice','points':5,'stem':'独立事件的交集概率为 $P(A)P(B)$，正确选项是？','options':['0.2','0.4','0.6','0.8'],
            'answer':'A','explanation':'独立事件概率相乘。','knowledge':'事件独立性','rubric':['计算正确'],'blanks':[]}]}


def create(client):
    response = client.post('/api/libraries', json={'name':'概率论共享库','description':'复习与错题'})
    assert response.status_code == 201
    return response.json()


def publish(client, lib, key='test-publish-id', content=None):
    response = client.post('/api/libraries/'+lib['id']+'/posts', json={'pack':content or pack(),'submission_id':key,'note':'第一章'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_three_accounts_membership_ownership_versions_and_download(cloud):
    owner, owner_cookie = account(cloud,'owner')
    lib = create(cloud)
    owner_post = publish(cloud,lib)
    member, member_cookie = account(cloud,'member')
    assert cloud.get('/api/libraries').json() == []
    assert cloud.get('/api/posts/'+owner_post).status_code == 404
    assert cloud.get('/api/posts/'+owner_post+'/download').status_code == 404
    assert cloud.post('/api/libraries/join',json={'invite_code':lib['invite_code']}).status_code == 200
    assert cloud.get('/api/posts/'+owner_post).json()['pack'] == pack()
    assert cloud.delete('/api/posts/'+owner_post).status_code == 403
    assert cloud.put('/api/posts/'+owner_post,json={'pack':pack(),'revision':1}).status_code == 403
    assert cloud.post('/api/libraries/'+lib['id']+'/invite').status_code == 403
    post = publish(cloud,lib)
    assert publish(cloud,lib) == post
    changed = pack(); changed['title'] = '修订后的概率练习'
    assert cloud.put('/api/posts/'+post,json={'pack':changed,'revision':1,'note':'纠正措辞'}).status_code == 200
    assert cloud.put('/api/posts/'+post,json={'pack':changed,'revision':1}).status_code == 409
    current = cloud.get('/api/posts/'+post).json()
    assert len(current['history']) == 2 and current['pack']['title'] == changed['title']
    assert cloud.get('/api/posts/'+post+'/download?revision=1').json() == pack()
    assert cloud.put('/api/posts/'+post+'/favorite?enabled=true').status_code == 200
    assert len(cloud.get('/api/libraries/'+lib['id']+'/posts?favorites=true').json()) == 1
    outsider, outsider_cookie = account(cloud,'outsider')
    assert cloud.get('/api/posts/'+post+'?revision=1').status_code == 404
    assert cloud.delete('/api/posts/'+post).status_code == 404
    use(cloud,owner_cookie)
    assert cloud.get('/api/libraries/'+lib['id']+'/posts?favorites=true').json() == []
    assert cloud.get('/api/libraries/'+lib['id']+'/posts?search=修订').json()[0]['id'] == post
    code = cloud.post('/api/libraries/'+lib['id']+'/invite').json()['invite_code']
    use(cloud,outsider_cookie)
    assert cloud.post('/api/libraries/join',json={'invite_code':lib['invite_code']}).status_code == 404
    assert cloud.post('/api/libraries/join',json={'invite_code':code}).status_code == 200
    use(cloud,owner_cookie)
    assert cloud.put(f"/api/libraries/{lib['id']}/members/{member['id']}?role=removed").status_code == 200
    use(cloud,member_cookie)
    assert cloud.get('/api/posts/'+post).status_code == 404
    assert cloud.get('/api/posts/'+post+'/download').status_code == 404
    assert cloud.post('/api/libraries/join',json={'invite_code':code}).status_code == 403
    assert cloud.post('/api/libraries/'+lib['id']+'/posts',json={'pack':pack(),'submission_id':'new-publish'}).status_code == 404
    use(cloud,owner_cookie)
    assert cloud.put(f"/api/libraries/{lib['id']}/members/{member['id']}?role=member").status_code == 200
    assert cloud.put(f"/api/libraries/{lib['id']}/members/{owner['id']}?role=removed").status_code == 422
    assert cloud.delete('/api/posts/'+post).status_code == 200
    use(cloud,member_cookie)
    assert cloud.get('/api/posts/'+post).status_code == 404


def test_auth_password_reset_hashes_and_csrf(cloud):
    user, cookie = account(cloud,'learner')
    with store.connection() as con:
        stored = dict(con.execute('SELECT * FROM users').fetchone())
        assert stored['password_hash'] != 'safe-test-password' and len(stored['salt']) == 32
        assert con.execute('SELECT token_hash FROM sessions').fetchone()[0] != cookie
    assert cloud.get('/api/me').json()['id'] == user['id']
    assert cloud.post('/api/libraries',json={'name':'bad'},headers={'Origin':'https://evil.example'}).status_code == 403
    assert cloud.put('/api/password',json={'old_password':'wrong','new_password':'new-test-password'}).status_code == 403
    assert cloud.put('/api/password',json={'old_password':'safe-test-password','new_password':'new-test-password'}).status_code == 200
    assert cloud.get('/api/me').status_code == 401
    assert cloud.post('/api/login',json={'username':'learner','password':'safe-test-password'}).status_code == 401
    assert cloud.post('/api/login',json={'username':'learner','password':'new-test-password'}).status_code == 200
    assert cloud.post('/api/logout').status_code == 200
    assert cloud.get('/api/me').status_code == 401
    assert cloud.get('/api/settings').status_code == 404
    assert cloud.post('/api/exams',json={}).status_code in (404,405)


@pytest.mark.parametrize('mutate',[
    lambda p: p.update(version=2),
    lambda p: p.update(api_key='must-not-be-shared'),
    lambda p: p['questions'][0].update(user_answer='private answer'),
    lambda p: p['questions'][0].update(sources=[{'document_id':'private-doc','page':1}]),
    lambda p: p['questions'][0].update(options=['only one']),
    lambda p: p['questions'][0].update(answer='AB'),
    lambda p: p.update(questions=[]),
])
def test_reject_private_or_malformed_pack(cloud,mutate):
    account(cloud,'author'); lib=create(cloud); data=copy.deepcopy(pack()); mutate(data)
    res=cloud.post('/api/libraries/'+lib['id']+'/posts',json={'pack':data,'submission_id':'bad-content'})
    assert res.status_code == 422
    assert cloud.get('/api/libraries/'+lib['id']+'/posts').json() == []


def test_body_limit_registration_code_and_rate_limit(cloud,monkeypatch):
    monkeypatch.setenv('LIBRARY_REGISTRATION_CODE','site-register-code')
    body={'username':'learner','password':'safe-test-password','nickname':'学生'}
    assert cloud.post('/api/register',json=body).status_code == 403
    assert cloud.post('/api/register',json={**body,'registration_code':'site-register-code'}).status_code == 201
    res=cloud.post('/api/login',content=b'x'*(3*1024*1024+1),headers={'Content-Type':'application/json'})
    assert res.status_code == 413
    for _ in range(30):
        assert cloud.post('/api/login',json={'username':'learner','password':'incorrect-password'}).status_code == 401
    assert cloud.post('/api/login',json={'username':'learner','password':'safe-test-password'}).status_code == 429


def test_production_https_cookie_and_preview_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA_DIR', tmp_path/'production-library')
    monkeypatch.setenv('LIBRARY_COOKIE_SECURE', 'true')
    monkeypatch.delenv('LIBRARY_PUBLIC_ORIGIN', raising=False)
    monkeypatch.delenv('LIBRARY_REGISTRATION_CODE', raising=False)
    with pytest.raises(RuntimeError, match='LIBRARY_PUBLIC_ORIGIN'):
        with TestClient(app):
            pass
    monkeypatch.setenv('LIBRARY_PUBLIC_ORIGIN', 'https://study.example')
    with TestClient(app, base_url='https://study.example') as client:
        assert client.post('/api/packs/preview', json=pack()).status_code == 401
        account(client, 'learner')
        signed_in = client.post('/api/login', json={'username':'learner','password':'safe-test-password'})
        cookie = signed_in.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        assert client.post('/api/packs/preview', json=pack(), headers={'Origin':'https://study.example'}).json() == pack()
        bad = pack(); bad['questions'][0]['self_score'] = 5
        assert client.post('/api/packs/preview', json=bad).status_code == 422
        assert client.post('/api/packs/preview', json=pack(), headers={'Origin':'http://study.example'}).status_code == 403
