import io
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from backend import backups, db, generation, practice
from tests.test_api import client, setup, exam_config, fake_generate  # noqa: F401


@pytest.fixture(autouse=True)
def clean_backups():
    yield
    with backups._pending_lock:
        for item in backups._pending.values(): item['temporary'].cleanup()
        backups._pending.clear()


def wrong_exam(client, setup, monkeypatch, count=2):
    monkeypatch.setattr(generation, 'generate_one', fake_generate)
    exam = client.post('/api/exams', json=exam_config(setup,count)).json()
    db.execute("UPDATE questions SET type='choice',options=?,answer='A' WHERE exam_id=?", (db.dump(['1','2','3','4']),exam['id']))
    exam = client.get('/api/exams/'+exam['id']).json()
    for q in exam['questions']:
        client.patch('/api/questions/'+q['id']+'/progress', json={'user_answer':'B','auto_score':True})
    return client.get('/api/exams/'+exam['id']).json()


def start(client, setup, submission='practice-test-01'):
    response = client.post('/api/review/practice',json={'course_id':setup[0]['id'],'submission_id':submission})
    assert response.status_code == 201, response.text
    return response.json()


def test_practice_is_local_independent_idempotent_and_keeps_original_attempts(client, setup, monkeypatch):
    original = wrong_exam(client, setup, monkeypatch)
    db.set_setting('api_key','')
    async def no_ai(*args): pytest.fail('practice must not call generation')
    monkeypatch.setattr(generation, 'generate_one', no_ai)
    exam = start(client,setup)
    again = start(client,setup)
    assert again['id'] == exam['id'] and exam['tokens'] == 0 and exam['status'] == 'ready'
    assert all(q['user_answer']=='' and q['self_score'] is None for q in exam['questions'])
    q = exam['questions'][0]; source_id = q['practice_source_id']
    for _ in range(2):
        saved = client.patch('/api/questions/'+q['id']+'/progress',json={'user_answer':'A','auto_score':True}).json()
        assert saved['self_score'] == q['points']
    source = db.one('SELECT * FROM questions WHERE id=?',(source_id,))
    assert source['user_answer'] == 'B' and source['self_score'] == 0 and source['is_wrong'] == 0
    assert len(client.get('/api/questions/'+source_id+'/attempts').json()) == 2
    assert len(client.get('/api/questions/'+q['id']+'/attempts').json()) == 1
    assert len(client.get('/api/review').json()) == 1
    assert client.get('/api/exams/'+original['id']).json()['tokens'] == original['tokens']
    assert client.post('/api/questions/'+q['id']+'/regenerate').status_code == 422
    assert client.post('/api/questions/'+q['id']+'/explanation').status_code == 422
    assert client.post('/api/exams/'+exam['id']+'/retry').status_code == 422


def test_practice_cap_course_filter_failure_and_deleted_submission(client, setup, monkeypatch):
    wrong_exam(client,setup,monkeypatch,12)
    exam = start(client,setup)
    assert len(exam['questions']) == 10
    assert len({q['practice_source_id'] for q in exam['questions']}) == 10
    other = client.post('/api/courses',json={'name':'其他课程'}).json()
    assert client.post('/api/review/practice',json={'course_id':other['id'],'submission_id':'different-empty'}).status_code == 422
    assert client.post('/api/review/practice',json={'course_id':other['id'],'submission_id':'practice-test-01'}).status_code == 409
    client.delete('/api/exams/'+exam['id'])
    assert client.post('/api/review/practice',json={'course_id':setup[0]['id'],'submission_id':'practice-test-01'}).status_code == 410


def test_manual_practice_scoring_and_changed_original_are_independent(client, setup, monkeypatch):
    original = wrong_exam(client,setup,monkeypatch)
    source_id = original['questions'][0]['id']
    db.execute("UPDATE questions SET type='calculation',options='[]' WHERE id=?",(source_id,))
    exam = start(client,setup)
    q = next(q for q in exam['questions'] if q['practice_source_id']==source_id)
    for _ in range(2):
        client.patch('/api/questions/'+q['id']+'/progress',json={'user_answer':'纸上计算','self_score':q['points']})
    assert len(client.get('/api/questions/'+source_id+'/attempts').json()) == 2
    assert db.one('SELECT is_wrong FROM questions WHERE id=?',(source_id,))['is_wrong'] == 0
    db.execute("UPDATE questions SET stem='原题已经改成另一道题',is_wrong=1 WHERE id=?",(source_id,))
    client.patch('/api/questions/'+q['id']+'/progress',json={'self_score':q['points']-1})
    assert len(client.get('/api/questions/'+source_id+'/attempts').json()) == 2
    assert db.one('SELECT is_wrong FROM questions WHERE id=?',(source_id,))['is_wrong'] == 1


def test_deleted_original_does_not_delete_practice_snapshot(client, setup, monkeypatch):
    original = wrong_exam(client,setup,monkeypatch)
    exam = start(client,setup)
    client.delete('/api/exams/'+original['id'])
    remaining = client.get('/api/exams/'+exam['id']).json()
    assert len(remaining['questions']) == 2
    assert all(q['practice_source_id'] is None for q in remaining['questions'])
    q=remaining['questions'][0]
    assert client.patch('/api/questions/'+q['id']+'/progress',json={'user_answer':'A','auto_score':True}).status_code == 200


def test_backup_download_restores_learning_data_without_credentials(client, setup, monkeypatch, tmp_path):
    wrong_exam(client,setup,monkeypatch)
    practice_exam=start(client,setup)
    secret = 'UNIQUE_SECRET_MUST_NOT_BE_EXPORTED_849213'
    db.set_setting('api_key',secret)
    db.set_setting('provider_text',db.dump({'api_key':secret,'enabled':False}))
    db.execute('CREATE TABLE retired_sessions(token TEXT)')
    db.execute('INSERT INTO retired_sessions VALUES (?)',(secret,))
    (db.DATA_DIR/'access-code.txt').write_text(secret)
    (db.DATA_DIR/'uploads'/'unreferenced-secret.txt').write_text(secret)
    result = client.post('/api/backups').json()
    path = backups._pending[result['url'].rsplit('/',1)[-1]]['path']
    response = client.get(result['url'])
    assert response.status_code == 200 and 'attachment' in response.headers['content-disposition']
    assert not path.exists() and client.get(result['url']).status_code == 404
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert all(secret.encode() not in archive.read(name) for name in archive.namelist())
        assert set(archive.namelist()) == {'data/study.sqlite3','data/uploads/'+setup[1]['id']+'.pdf','manifest.json','恢复说明.txt'}
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['counts']['exams'] == 2
        restore = tmp_path/'restore'; archive.extractall(restore)
    assert db.setting('api_key') == secret  # Export never changes the running app.
    with monkeypatch.context() as m:
        m.setattr(db,'DATA_DIR',restore/'data')
        db.init_db()
        assert db.setting('api_key','') == '' and db.one('SELECT count(*) AS n FROM sessions')['n'] == 0
        assert len(db.rows('SELECT * FROM questions WHERE exam_id=?',(practice_exam['id'],))) == 2
        assert len(db.rows('SELECT * FROM attempts')) == 2
        assert db.rows('PRAGMA foreign_key_check') == []


def test_backup_missing_document_fails_and_requires_auth(client, setup):
    (db.DATA_DIR/'uploads'/(setup[1]['id']+'.pdf')).unlink()
    response=client.post('/api/backups')
    assert response.status_code==409 and '缺失' in response.text and not backups._pending
    client.cookies.clear()
    assert client.post('/api/backups').status_code==401
    assert client.get('/api/backups/not-real').status_code==401


def test_backup_build_guard_and_expiry(client, setup, monkeypatch):
    backups._building.acquire()
    try: assert client.post('/api/backups').status_code==409
    finally: backups._building.release()
    result=client.post('/api/backups').json()
    item=next(iter(backups._pending.values()))
    monkeypatch.setattr(backups.time,'monotonic',lambda:item['created']+backups.TTL+1)
    assert client.get(result['url']).status_code==404
    assert not item['path'].exists()
