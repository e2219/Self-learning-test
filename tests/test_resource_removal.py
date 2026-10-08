from backend import db
from tests.test_api import client, setup  # noqa: F401


def test_resource_routes_removed_and_providers_preserved(client, setup):
    for path in ('search?q=probability&site=en', 'preview?page_id=1&site=en'):
        assert client.get('/api/web-resources/' + path).status_code == 404
    assert client.post('/api/web-resources/import', json={}).status_code in (404, 405)
    assert client.get('/api/settings').json()['providers']['text']['active_name'] == 'DeepSeek'
    assert not db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='web_sources'")


def test_previously_imported_exam_remains_editable(client, setup):
    course = setup[0]
    source = {'document_id': 'web:old', 'page': 1, 'name': '旧摘录', 'imported': True,
              'url': 'https://zh.wikiversity.org/w/index.php?oldid=123', 'license': 'CC BY-SA 4.0'}
    db.execute("INSERT INTO exams(id,course_id,title,config,status) VALUES (?,?,?,?,'ready')",
               ('old-import', course['id'], '旧摘录卷', db.dump({'origin': 'web_import', 'ranges': []})))
    db.execute("""INSERT INTO questions(id,exam_id,position,type,points,status,stem,answer,explanation,knowledge,sources)
               VALUES ('old-q','old-import',1,'calculation',5,'ready',?,?,?,?,?)""",
               ('求两个独立事件同时发生的概率。', '概率相乘', '依据独立事件定义。', '独立事件', db.dump([source])))
    exam = client.get('/api/exams/old-import').json()
    question = exam['questions'][0]
    assert question['sources'][0]['license'] == 'CC BY-SA 4.0'
    question['explanation'] = '根据独立事件乘法公式。'
    edited = client.put('/api/questions/old-q', json=question)
    assert edited.status_code == 200, edited.text
    assert edited.json()['sources'][0]['modified']
    assert client.patch('/api/questions/old-q/progress', json={'user_answer': '概率相乘', 'self_score': 5}).status_code == 200
