import json

from backend import db, generation
from tests.test_api import client, setup, exam_config, fake_generate  # noqa: F401


def test_export_import_excludes_private_fields_and_preserves_personal_progress(client,setup,monkeypatch):
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    exam=client.post('/api/exams',json=exam_config(setup)).json()
    original=client.get('/api/exams/'+exam['id']).json()
    q=original['questions'][0]
    client.patch('/api/questions/'+q['id']+'/progress',json={'user_answer':'个人私有答案','self_score':3,'is_favorite':True})
    exported=client.get('/api/exams/'+exam['id']+'/share')
    assert exported.status_code == 200
    pack=exported.json()
    serialized=json.dumps(pack,ensure_ascii=False)
    for private in ('user_answer','self_score','sources','document_id','api_key','个人私有答案',setup[1]['name']):
        assert private not in serialized
    assert len(pack['questions'])==2
    assert client.get('/api/questions/'+q['id']+'/share').json()['kind']=='mistakes'
    assert len(client.get('/api/review/share').json()['questions'])==1
    imported=client.post('/api/imports/study-pack',json=pack)
    assert imported.status_code == 201, imported.text
    new=imported.json()
    assert new['config']['imported'] and new['id']!=original['id']
    assert new['tokens']==0 and len(new['questions'])==2
    assert all(q['self_score'] is None and q['user_answer']=='' and not q['is_wrong'] and not q['is_favorite'] for q in new['questions'])
    assert new['questions'][0]['stem']==q['stem']
    assert client.post('/api/questions/'+new['questions'][0]['id']+'/regenerate').status_code==422
    assert client.post('/api/exams/'+new['id']+'/retry').status_code==422
    client.patch('/api/questions/'+new['questions'][0]['id']+'/progress',json={'user_answer':'我的新答案','self_score':8})
    assert db.one('SELECT self_score FROM questions WHERE id=?',(q['id'],))['self_score']==3
    assert client.get('/api/settings').json()['has_key']
