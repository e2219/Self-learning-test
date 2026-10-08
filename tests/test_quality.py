"""Regression cases modelled on peer feedback, not a model accuracy benchmark."""
import asyncio
import copy
import json

import httpx
import pytest

from backend import generation, quality
from backend.models import GeneratedQuestion
from tests.test_api import client, setup, valid_payload  # noqa: F401
from tests.test_generation_recovery import result


def blind(**overrides):
    return dict(answer='A', option_judgments=[{'label': x, 'verdict': 'correct' if x == 'A' else 'incorrect', 'reason': '依据资料逐项判断'} for x in 'ABCD'], target_matches=True, type_matches=True, supported=True, unambiguous=True, duplicate=False, issues=[], **overrides)


def test_blind_review_does_not_see_proposed_answer_and_checks_consistency():
    calls = []
    async def call(messages):
        task = json.loads(messages[1]['content']); calls.append(task)
        if task['stage'] == 'blind_review':
            assert set(task['question']) == {'stem', 'options'}
            return result(blind())
        return result(dict(answer_matches=True, explanation_consistent=True, evidence_supported=True, issues=[]))
    review = asyncio.run(quality.review_question(call, GeneratedQuestion(**valid_payload()), 'choice', [], [], {}))
    assert review['status'] == 'passed' and len(calls) == 2


@pytest.mark.parametrize('fault', ['two_answers', 'uncertain', 'wrong_type', 'unsupported', 'duplicate', 'wrong_answer', 'explanation', 'malformed'])
def test_known_bad_questions_cannot_pass(fault):
    calls = []
    async def call(messages):
        task = json.loads(messages[1]['content']); calls.append(task)
        payload = blind()
        if fault == 'two_answers': payload['option_judgments'][1]['verdict'] = 'correct'
        if fault == 'uncertain': payload['option_judgments'][1]['verdict'] = 'uncertain'
        if fault == 'wrong_type': payload['type_matches'] = False
        if fault == 'unsupported': payload['supported'] = False
        if fault == 'duplicate': payload['duplicate'] = True
        if fault == 'wrong_answer': payload['answer'] = 'B'
        if fault == 'malformed': payload = {'type_matches': 'true'}
        if task['stage'] == 'consistency_review':
            payload = dict(answer_matches=True, explanation_consistent=False, evidence_supported=True, issues=['解析承认 B 也正确'])
        return result(payload)
    with pytest.raises(quality.ReviewError):
        asyncio.run(quality.review_question(call, GeneratedQuestion(**valid_payload()), 'choice', [], [], {}))
    assert len(calls) == (2 if fault == 'explanation' else 1)


def test_fill_contract_and_canonical_answers():
    payload = {**valid_payload(), 'options': [], 'stem': '催化反应的生物分子称为 [[blank:1]]。', 'blanks': [{'answer': '酶', 'alternatives': ['enzyme']}]}
    q = generation.validate_content(payload, 'fill', [{'document_id': 'doc', 'page': 1}], [])
    assert q.answer == '（1）酶（亦可：enzyme）'
    for stem in ['请详细解释酶的作用机制。', '填写 [[blank:2]]。', '填写 [[blank:1]] 和 [[blank:1]]。']:
        with pytest.raises(generation.OutputValidationError):
            generation.validate_content({**payload, 'stem': stem}, 'fill', [{'document_id': 'doc', 'page': 1}], [])


def test_review_failure_repairs_and_counts_all_requests(client, setup, monkeypatch):
    calls = []
    original = httpx.AsyncClient
    def handler(req):
        task = json.loads(json.loads(req.content)['messages'][1]['content']); calls.append(task)
        stage = task.get('stage')
        if stage == 'blind_review':
            payload = blind()
            if len(calls) == 2: payload['option_judgments'][1]['verdict'] = 'correct'
        elif stage == 'consistency_review':
            assert 'rubric' not in task['question']
            payload = dict(answer_matches=True, explanation_consistent=True, evidence_supported=True, issues=[])
        else:
            assert 'rubric' not in task['output_schema']['properties']
            assert 'rubric' not in task['output_example_structure_only']
            payload = valid_payload()
            payload.pop('rubric')
        return httpx.Response(200, json=result(payload))
    monkeypatch.setattr(generation.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    q, usage = asyncio.run(generation.generate_one({'type': 'choice', 'points': 5}, {'difficulty': '基础巩固'}, [{'document_id': 'doc', 'page': 1}], []))
    assert usage == 500 and q._review['status'] == 'passed'
    assert q.rubric == []
    assert calls[2]['validation_feedback']['code'] == 'QUESTION_REVIEW'
