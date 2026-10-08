import asyncio
import copy
import json

import httpx
import pytest

from backend import db, generation
from tests.review_fixtures import review_response
from tests.test_api import client, setup, valid_payload, exam_config  # noqa: F401

REFS = [{'document_id': 'doc', 'page': 1}]


def previous(payload=None, kind='choice'):
    return [{'type': kind, **copy.deepcopy(payload or valid_payload())}]


def result(payload, usage=100, finish='stop'):
    return {'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload}}], 'usage': {'total_tokens': usage}}


def adapter(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(generation.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda req: review_response(req) or handler(req)), **kw))


def test_same_generic_choice_stem_different_options_is_not_duplicate():
    q = valid_payload()
    q['options'] = ['确定事件', '随机事件', '不可能事件', '基本事件']
    assert generation.validate_content(q, 'choice', REFS, previous()).options == q['options']


def test_reordered_options_and_changed_answer_still_duplicate():
    q = valid_payload()
    q['options'].reverse()
    q['answer'] = 'D'
    with pytest.raises(generation.DuplicateQuestionError):
        generation.validate_content(q, 'choice', REFS, previous())


@pytest.mark.parametrize('new_stem', [
    '设随机变量 X 取值满足 $X>1$，则这个条件的补事件为[[blank:1]]。',
    '设随机变量 X 取值满足 $X<2$，则这个条件的补事件为[[blank:1]]。',
    '设随机变量 X 取值不满足 $X<1$，则这个条件的补事件为[[blank:1]]。',
])
def test_similar_fill_stems_with_different_math_or_negation_are_kept(new_stem):
    old = valid_payload()
    old.update(options=[], blanks=[{"answer": "补事件", "alternatives": []}], stem='设随机变量 X 取值满足 $X<1$，则这个条件的补事件为[[blank:1]]。')
    q = {**old, 'stem': new_stem}
    assert generation.validate_content(q, 'fill', REFS, previous(old, 'fill')).stem == new_stem


def test_identical_fill_stems_still_rejected():
    old = valid_payload()
    old.update(options=[], blanks=[{"answer": "补事件", "alternatives": []}], stem='写出随机事件的补事件定义：[[blank:1]]。')
    q = {**old, 'stem': '写出随机事件的补事件定义：[[blank:1]]。\n', 'answer': '另一份答案不能使题干成为新题'}
    with pytest.raises(generation.DuplicateQuestionError):
        generation.validate_content(q, 'fill', REFS, previous(old, 'fill'))


def test_duplicate_feedback_changes_angle_and_accounts_all_calls(client, setup, monkeypatch):
    requests = []
    fresh = valid_payload()
    fresh['stem'] = '掷一枚均匀硬币，写出一个不可能发生的事件。'
    def handler(request):
        body = json.loads(request.content)
        user = json.loads(body['messages'][1]['content'])
        requests.append(user)
        return httpx.Response(200, json=result(valid_payload() if len(requests) == 1 else fresh))
    adapter(monkeypatch, handler)
    q, usage = asyncio.run(generation.generate_one({'type': 'choice', 'points': 5, 'position': 2}, {'difficulty': '基础巩固'}, REFS, previous()))
    assert q.stem == fresh['stem'] and usage == 200 and len(requests) == 2
    assert requests[0]['avoid_questions'][0]['options'] == valid_payload()['options']
    assert requests[1]['validation_feedback']['code'] == 'QUESTION_DUPLICATE'
    assert requests[0]['task']['suggested_angle'] != requests[1]['task']['suggested_angle']
    assert requests[0]['reference_material'] == requests[1]['reference_material']


@pytest.mark.parametrize('broken,code', [
    (r'{"stem":"$A\cup B$"}', 'QUESTION_JSON'),
    ({'stem': '不完整的数学题干'}, 'QUESTION_FORMAT'),
    ({**valid_payload(), 'answer': 'AB'}, 'QUESTION_FORMAT'),
    ({**valid_payload(), 'options': ['相同选项'] * 4}, 'QUESTION_FORMAT'),
    ({**valid_payload(), 'sources': [{'document_id': 'other', 'page': 99}]}, 'QUESTION_FORMAT'),
    ({**valid_payload(), 'answer': '\x0crac'}, 'QUESTION_LATEX_ESCAPE'),
])
def test_validation_failures_are_repaired_with_specific_feedback(client, setup, monkeypatch, broken, code):
    calls = []
    def handler(request):
        user = json.loads(json.loads(request.content)['messages'][1]['content'])
        calls.append(user)
        return httpx.Response(200, json=result(broken if len(calls) == 1 else valid_payload()))
    adapter(monkeypatch, handler)
    _, usage = asyncio.run(generation.generate_one({'type': 'choice', 'points': 5}, {'difficulty': '基础巩固'}, REFS, []))
    assert len(calls) == 2 and usage == 200
    assert calls[1]['validation_feedback']['code'] == code


def test_complete_json_fence_and_labelled_option_map_are_safe_to_normalize():
    payload = valid_payload()
    payload['options'] = dict(zip('ABCD', payload['options']))
    payload['answer'] = ' a '
    q = generation.decode_question_response(result('```json\n'+json.dumps(payload)+'\n```'), 'choice', REFS, [])
    assert q.options == valid_payload()['options'] and q.answer == 'A'


@pytest.mark.parametrize('kind', ['duplicate', 'format', 'truncated'])
def test_retry_budget_is_bounded_and_failed_usage_preserved(client, setup, monkeypatch, kind):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=result({} if kind == 'format' else valid_payload(), finish='length' if kind == 'truncated' else 'stop'))
    adapter(monkeypatch, handler)
    with pytest.raises(generation.GenerationError, match='已尝试 3 次') as error:
        asyncio.run(generation.generate_one({'type': 'choice', 'points': 5}, {'difficulty': '基础巩固'}, REFS, previous() if kind == 'duplicate' else []))
    assert len(calls) == 3 and error.value.tokens == 300


@pytest.mark.parametrize('status', [401, 402, 429, 500])
def test_provider_failure_never_triggers_automatic_content_retries(client, setup, monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, text='PRIVATE-RESPONSE')
    adapter(monkeypatch, handler)
    with pytest.raises(generation.GenerationError) as error:
        asyncio.run(generation.generate_one({'type': 'choice', 'points': 5}, {'difficulty': '基础巩固'}, REFS, []))
    assert len(calls) == 1 and 'PRIVATE-RESPONSE' not in str(error.value)


def test_worker_recovers_existing_failed_exam_without_replacing_ready_question(client, setup, monkeypatch):
    course, doc = setup
    first = valid_payload()
    first['sources'] = [{'document_id': doc['id'], 'page': 1}]
    calls = []
    state = {'retry': False}
    def handler(request):
        user = json.loads(json.loads(request.content)['messages'][1]['content'])
        calls.append(user)
        payload = copy.deepcopy(first)
        if state['retry']:
            payload['stem'] = '一个随机试验的样本空间包含哪些基本结果？'
        return httpx.Response(200, json=result(payload))
    adapter(monkeypatch, handler)
    config = exam_config(setup)
    config['rules'] = [{'type': 'choice', 'count': 2, 'points': 5}]
    config['max_attempts'] = 3
    exam_id = client.post('/api/exams', json=config).json()['id']
    before = client.get(f'/api/exams/{exam_id}').json()
    assert before['status'] == 'partial' and before['tokens'] == 400
    assert before['questions'][1]['error'].endswith('（QUESTION_DUPLICATE）')
    assert len(calls) == 4
    state['retry'] = True
    client.post(f'/api/exams/{exam_id}/retry')
    after = client.get(f'/api/exams/{exam_id}').json()
    assert after['status'] == 'ready' and after['tokens'] == 500
    assert after['questions'][0] == before['questions'][0]
    assert len(calls[-1]['avoid_questions']) == 1


def test_pause_prevents_additional_automatic_calls(client, setup, monkeypatch):
    calls = []
    def handler(request):
        calls.append(1)
        db.execute("UPDATE exams SET status='paused' WHERE status='generating'")
        return httpx.Response(200, json=result({}))
    adapter(monkeypatch, handler)
    exam_id = client.post('/api/exams', json=exam_config(setup)).json()['id']
    exam = client.get(f'/api/exams/{exam_id}').json()
    assert len(calls) == 1 and exam['status'] == 'paused' and exam['tokens'] == 100
    assert all(q['status'] == 'pending' for q in exam['questions'])


def test_empty_message_is_retried_without_crashing_feedback(client, setup, monkeypatch):
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': None}], 'usage': None})
        return httpx.Response(200, json=result(valid_payload()))
    adapter(monkeypatch, handler)
    question, usage = asyncio.run(generation.generate_one({'type': 'choice', 'points': 5}, {'difficulty': '基础巩固'}, REFS, []))
    assert question.answer == 'A' and usage == 100 and len(calls) == 2


def test_target_passage_prioritizes_uncovered_material_from_same_sources():
    seen = '独立事件的定义与乘法公式是本段主要讨论的知识内容。'
    unseen = '随机试验具有可重复性，所有可能结果构成样本空间。'
    refs = [{'document_id': 'doc', 'page': 3, 'text': seen + unseen}]
    target = generation.select_target_passage(refs, [{'stem': seen, 'knowledge': seen, 'options': []}], 1)
    assert target == {'document_id': 'doc', 'page': 3, 'text': unseen}


def test_short_or_formula_only_material_does_not_invent_a_target():
    assert generation.select_target_passage([{'document_id': 'doc', 'page': 1, 'text': '$x=1$'}], [], 1) is None
