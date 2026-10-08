import pytest
from backend import db, generation, planning
from tests.test_api import client, setup, exam_config, fake_generate  # noqa: F401


def test_exam_and_course_deletion_scope(client, setup, monkeypatch):
    course, doc = setup
    monkeypatch.setattr(generation, 'generate_one', fake_generate)
    first = client.post('/api/exams', json=exam_config(setup, 1)).json()['id']
    second = client.post('/api/exams', json=exam_config(setup, 1)).json()['id']
    question = client.get('/api/exams/'+first).json()['questions'][0]
    assert client.patch('/api/questions/'+question['id']+'/progress', json={'user_answer':'test','self_score':0,'is_wrong':True,'is_favorite':True}).status_code == 200
    assert db.one('SELECT id FROM attempts WHERE question_id=?',(question['id'],))
    assert client.delete('/api/exams/'+first).status_code == 200
    assert client.get('/api/exams/'+first).status_code == 404
    assert not db.one('SELECT id FROM questions WHERE exam_id=?',(first,))
    assert not db.one('SELECT id FROM attempts WHERE question_id=?',(question['id'],))
    assert client.get('/api/exams/'+second).status_code == 200
    assert (db.DATA_DIR/'uploads'/f"{doc['id']}.pdf").exists()
    assert client.delete('/api/courses/'+course['id']).status_code == 200
    assert client.get('/api/exams/'+second).status_code == 404
    assert not db.one('SELECT id FROM documents WHERE id=?',(doc['id'],))
    assert not (db.DATA_DIR/'uploads'/f"{doc['id']}.pdf").exists()


@pytest.mark.parametrize('status,active', [('queued',False),('running',False),('cancelled',True)])
def test_course_deletion_waits_for_planning_to_finish(client,setup,monkeypatch,status,active):
    course,doc=setup
    db.execute('INSERT INTO exam_plans(id,course_id,config,fingerprint,materials,status) VALUES (?,?,?,?,?,?)',
        ('delete-plan',course['id'],db.dump(exam_config(setup)),'','[]',status))
    monkeypatch.setattr(planning,'active_plans',{'delete-plan'} if active else set())
    response=client.delete('/api/courses/'+course['id'])
    assert response.status_code==409 and '规划' in response.json()['detail']
    assert db.one('SELECT id FROM courses WHERE id=?',(course['id'],))
    assert (db.DATA_DIR/'uploads'/f"{doc['id']}.pdf").exists()
