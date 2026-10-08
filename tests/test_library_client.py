import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import db, library_client, security
from backend.main import app
from backend.library import store
from backend.library.main import app as cloud_app
from tests.test_library import pack, account, create, publish, use


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path/'personal')
    monkeypatch.setattr(store, 'DATA_DIR', tmp_path/'cloud')
    monkeypatch.setenv('STUDY_ACCESS_CODE', 'test-access-123')
    monkeypatch.setenv('LIBRARY_COOKIE_SECURE', 'false')
    monkeypatch.delenv('LIBRARY_PUBLIC_ORIGIN', raising=False)
    monkeypatch.delenv('LIBRARY_REGISTRATION_CODE', raising=False)
    security.failures.clear()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(library_client.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.ASGITransport(app=cloud_app), **kw))
    with TestClient(cloud_app) as cloud, TestClient(app) as local:
        assert local.post('/api/login', json={'code':'test-access-123'}).status_code == 200
        yield local, cloud


def connect(local):
    res = local.put('/api/library/connection', json={'server':'http://127.0.0.1:8001'})
    assert res.status_code == 200, res.text


def login_shared(local, name='student'):
    base = '/api/library/remote'
    assert local.post(base+'/register', json={'username':name,'password':'student-password','nickname':name}).status_code == 200
    assert local.post(base+'/login', json={'username':name,'password':'student-password'}).status_code == 200


def test_bridge_session_isolation_logout_and_filtered_paths(bridge):
    local, cloud = bridge
    connect(local); login_shared(local)
    cookie = local.cookies.get('study_session')
    assert local.get('/api/library/remote/me').json()['username'] == 'student'
    assert local.get('/api/library/remote/settings').status_code == 404
    assert local.get('/api/library/remote/health').status_code == 404
    assert local.get('/api/library/connection').json() == {'server':'http://127.0.0.1:8001','connected':True}
    assert local.post('/api/library/remote/logout').status_code == 200
    assert local.get('/api/library/remote/me').status_code == 424
    assert local.get('/api/session').status_code == 200
    assert local.post('/api/library/remote/login', json={'username':'student','password':'student-password'}).status_code == 200
    local.cookies.clear()
    assert local.get('/api/library/remote/me').status_code == 401
    local.post('/api/login', json={'code':'test-access-123'})
    assert local.get('/api/library/connection').json()['connected'] is False
    assert local.get('/api/library/remote/me').status_code == 409
    local.cookies.clear(); local.cookies.set('study_session',cookie)
    assert local.get('/api/library/remote/me').status_code == 200
    local.post('/api/logout')
    assert db.one('SELECT * FROM library_connections') is None


@pytest.mark.parametrize('server', ['http://example.com', 'https://user:secret@example.com','https://example.com/path', 'https://example.com?token=bad', 'file:///tmp/test'])
def test_invalid_server_rejected(bridge, server):
    local, _ = bridge
    assert local.put('/api/library/connection', json={'server':server}).status_code == 422


def test_password_join_rotation_roles_and_legacy_invite(bridge):
    local, cloud = bridge
    owner, owner_cookie = account(cloud, 'creator')
    lib = cloud.post('/api/libraries',json={'name':'共享库','access_password':'shared-pass-123'}).json()
    connect(local); login_shared(local)
    assert local.post('/api/library/remote/libraries/join',json={'library_id':lib['id'],'password':'wrong'}).status_code == 404
    assert local.post('/api/library/remote/libraries/join',json={'library_id':lib['id'],'password':'shared-pass-123'}).status_code == 200
    student = local.get('/api/library/remote/me').json()
    assert local.put('/api/library/remote/libraries/'+lib['id']+'/access-password',json={'password':'new-password'}).status_code == 403
    assert cloud.put('/api/libraries/'+lib['id']+'/access-password',json={'password':'new-password'}).status_code == 200
    assert local.get('/api/library/remote/libraries/'+lib['id']).status_code == 200
    with store.connection() as con:
        row = dict(con.execute('SELECT * FROM libraries').fetchone())
        assert row['access_hash'] not in ('new-password','shared-pass-123')
        assert row['access_salt']
    outsider, _ = account(cloud,'outsider')
    for body in [{'library_id':lib['id'],'password':'shared-pass-123'},{'invite_code':lib['invite_code']}]:
        assert cloud.post('/api/libraries/join',json=body).status_code == 404
    assert cloud.post('/api/libraries/join',json={'library_id':lib['id'],'password':'new-password'}).status_code == 200
    use(cloud,owner_cookie)
    cloud.put(f"/api/libraries/{lib['id']}/members/{student['id']}?role=removed")
    assert local.post('/api/library/remote/libraries/join',json={'library_id':lib['id'],'password':'new-password'}).status_code == 403


def test_direct_publish_import_version_duplicate_and_scores(bridge):
    local, cloud = bridge
    owner, cookie = account(cloud,'creator'); lib = create(cloud)
    post_id = publish(cloud,lib)
    connect(local); login_shared(local)
    local.post('/api/library/remote/libraries/join',json={'library_id':lib['id'],'password':lib['access_password']})
    target = local.post('/api/courses',json={'name':'自己的课程'}).json()
    body = {'post_id':post_id,'revision':1,'course_id':target['id'],'submission_id':'import-0001'}
    result = local.post('/api/library/imports',json=body)
    assert result.status_code == 200, result.text
    exam_id = result.json()['id']
    assert local.post('/api/library/imports',json={**body,'submission_id':'import-0002'}).json()['id'] == exam_id
    exam = local.get('/api/exams/'+exam_id).json()
    assert exam['course_id'] == target['id']
    assert exam['config']['shared_source']['revision'] == 1
    assert exam['config']['shared_source']['author'] == 'creator'
    assert not exam['questions'][0]['user_answer'] and exam['questions'][0]['self_score'] is None
    assert local.patch('/api/questions/'+exam['questions'][0]['id']+'/progress',json={'user_answer':'A','auto_score':True}).status_code == 200
    copy_body = {**body,'new_copy':True,'submission_id':'copy-0001'}
    copied = local.post('/api/library/imports',json=copy_body).json()['id']
    assert copied != exam_id
    assert local.post('/api/library/imports',json=copy_body).json()['id'] == copied
    assert local.get('/api/exams/'+copied).json()['questions'][0]['self_score'] is None
    revised = pack(); revised['title'] = '新版共享试卷'
    assert cloud.put('/api/posts/'+post_id,json={'pack':revised,'revision':1}).status_code == 200
    status = local.get('/api/library/import-status/'+post_id).json()
    assert status['revision'] == 2 and len(status['copies']) == 2
    updated = local.post('/api/library/imports',json={**body,'revision':2}).json()['id']
    assert updated not in (exam_id,copied)
    assert local.get('/api/exams/'+exam_id).json()['questions'][0]['self_score'] == 5
    # Local export, explicit publish, remote download: only the portable content crosses.
    exported = local.get('/api/exams/'+exam_id+'/share').json()
    newpost = local.post('/api/library/remote/libraries/'+lib['id']+'/posts',json={'pack':exported,'submission_id':'publish-0001'})
    assert newpost.status_code == 200, newpost.text
    remote_id = newpost.json()['id']
    downloaded = local.get('/api/library/remote/posts/'+remote_id+'/download?revision=1')
    assert downloaded.json() == exported and 'attachment' in downloaded.headers['content-disposition']
    assert 'shared_source' not in downloaded.text and 'self_score' not in downloaded.text
    assert len(local.get('/api/exams').json()) == 3
    assert local.post('/api/library/imports',json={**body,'course_id':'missing','new_copy':True,'submission_id':'bad-course'}).status_code == 404
    student = local.get('/api/library/remote/me').json()
    cloud.put(f"/api/libraries/{lib['id']}/members/{student['id']}?role=removed")
    assert local.post('/api/library/imports',json=body).status_code == 404
    assert local.get('/api/exams/'+exam_id).status_code == 200


def test_password_schema_upgrade_preserves_existing_library(tmp_path, monkeypatch):
    monkeypatch.setattr(store,'DATA_DIR',tmp_path)
    with sqlite3.connect(tmp_path/'library.sqlite3') as con:
        con.executescript("""CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,nickname TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL);
        CREATE TABLE libraries(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,owner_id TEXT NOT NULL REFERENCES users(id),invite_hash TEXT NOT NULL UNIQUE);
        INSERT INTO users VALUES ('user','legacy','旧成员','salt','hash');
        INSERT INTO libraries VALUES ('library','旧学习库','','user','invite');""")
    store.initialize(); store.initialize()
    with store.connection() as con:
        row = dict(con.execute('SELECT * FROM libraries').fetchone())
        assert row['name'] == '旧学习库' and row['owner_id'] == 'user' and row['invite_hash'] == 'invite'
        assert row['access_hash'] == '' and row['access_salt'] == ''


def test_switch_server_clears_shared_login_and_csrf_keeps_connection(bridge):
    local, _ = bridge
    connect(local); login_shared(local)
    res = local.put('/api/library/connection',json={'server':'http://127.0.0.1:8002'},headers={'Origin':'https://evil.example'})
    assert res.status_code == 403
    assert local.get('/api/library/remote/me').status_code == 200
    assert local.put('/api/library/connection',json={'server':'http://127.0.0.1:8002'}).status_code == 200
    assert local.get('/api/library/remote/me').status_code == 424
    assert local.get('/api/session').status_code == 200
    assert library_client.normalize_server('https://Study.Example:443/') == 'https://study.example'


def test_concurrent_import_retries_create_one_exam(bridge):
    from concurrent.futures import ThreadPoolExecutor
    local, cloud = bridge
    account(cloud,'creator'); lib=create(cloud); post_id=publish(cloud,lib)
    connect(local); login_shared(local)
    local.post('/api/library/remote/libraries/join',json={'invite_code':lib['invite_code']})
    body={'post_id':post_id,'revision':1,'submission_id':'concurrent-import'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda _: local.post('/api/library/imports',json=body), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()['id'] for r in responses}) == 1
    assert len(local.get('/api/exams').json()) == 1
    assert local.get('/api/library/remote/libraries/'+lib['id']+'/posts?search=creator').json()[0]['id'] == post_id
