import asyncio
from fractions import Fraction
import json

import httpx
import pytest
from backend import generation, local_quality, quality
from backend.models import GeneratedQuestion
from tests.test_api import client, setup, valid_payload  # noqa: F401
from tests.test_generation_recovery import result
from tests.test_quality import blind


def question(**fields):
    return GeneratedQuestion(**{**valid_payload(), **fields})


@pytest.mark.parametrize('expression,expected', [
    (r'\frac{1}{2}+\frac{1}{3}', Fraction(5,6)),
    (r'\frac{1}{\frac{2}{3}}', Fraction(3,2)),
    (r'\binom{4}{2}*(1/2)^{4}', Fraction(3,8)),
    ('50%', Fraction(1,2)), ('0.1+0.2', Fraction(3,10)), ('4!/(2!*2!)', Fraction(6)),
    (r'\left(1-\frac{1}{2}\right)^2', Fraction(1,4)),
])
def test_bounded_exact_arithmetic(expression,expected):
    assert local_quality.numeric(expression)==expected


@pytest.mark.parametrize('expression', ['x+1', '1/0', '__import__("os").system("echo bad")', '10**1000000', 'factorial(100000)', '1e99999', '2**(2**100)', '1+'*1000, '1//2', 'sum([1,2])', '9'*500])
def test_unsupported_or_resource_heavy_expressions_are_skipped(expression):
    assert local_quality.numeric(expression) is None


def test_wrong_closed_equation_rejected_before_semantic_review():
    q=question(explanation=r'依据独立性计算 $P(A\cap B)=0.4\times 0.5=0.3$。')
    with pytest.raises(local_quality.LocalQualityError,match='数值等式'):
        local_quality.check(q,'choice')
    q.explanation=r'依据独立性计算 $P(A\cap B)=0.4\times 0.5=0.2$。'
    checks=local_quality.check(q,'choice')
    assert checks['arithmetic']==1 and checks['skipped']==1


@pytest.mark.parametrize('explanation', [
    r'取近似值 $1/3=0.33$。', r'反例中的等式 $1+1=3$ 不成立。',
    r'选项 B 把结果误写为 $1+1=3$。', r'假设 $0=1$，推出矛盾。',
    r'选项 B 中有 $1+1=3$，因此选择 A。', r'按题目要求保留两位小数：$2/3=0.67$。', r'表达式 $x^2=4$ 依赖未知变量。',
])
def test_rounding_counterexamples_and_symbolic_claims_not_mislabelled(explanation):
    assert local_quality.check(question(explanation=explanation),'choice')['arithmetic']==0


def test_equivalent_numeric_options_rejected_only_for_value_questions():
    q=question(stem='计算下列事件发生的概率为多少？',options=['$0.5$',r'$\frac{1}{2}$','$0.25$','$1$'])
    with pytest.raises(local_quality.LocalQualityError,match='数值完全相同'):local_quality.check(q,'choice')
    assert local_quality.check(q,'multiple_choice')['numeric_options']==0
    q.stem='下列哪个选项是用最简分数表示的结果？'
    assert local_quality.check(q,'choice')['numeric_options']==0
    q.stem='下列哪个表达式使用了分数形式？'
    assert local_quality.check(q,'choice')['numeric_options']==0


def test_logic_truth_table_and_false_equivalence():
    q=question(explanation=r'使用德摩根律 $\neg(p\land q)\equiv\neg p\lor\neg q$。')
    assert local_quality.check(q,'choice')['logic']==1
    q.explanation=r'依据等价关系 $p\to q\equiv \neg p\lor q$。'
    assert local_quality.check(q,'choice')['logic']==1
    q.explanation=r'应用恒等式 $p\lor q\equiv p\land q$。'
    with pytest.raises(local_quality.LocalQualityError,match='真值表'):local_quality.check(q,'choice')
    q.explanation=r'注意 $p\lor q\equiv p\land q$ 不成立。'
    assert local_quality.check(q,'choice')['logic']==0
    q.explanation=r'量词公式 $\forall x P(x)\equiv P(a)$。'
    assert local_quality.check(q,'choice')['logic']==0


def test_local_failure_repairs_without_paying_for_review_of_bad_candidate(client,setup,monkeypatch):
    calls=[]
    original=httpx.AsyncClient
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']);calls.append(task)
        stage=task.get('stage','generation')
        if stage=='blind_review': payload=blind()
        elif stage=='consistency_review':
            assert 'reason' not in json.dumps(task['independent_solution'])
            payload=dict(answer_matches=True,explanation_consistent=True,evidence_supported=True,issues=[])
        else:
            payload=valid_payload()
            payload['explanation']=r'计算得到 $1/2+1/3=5/6$。' if len(calls)>1 else r'计算得到 $1/2+1/3=1$。'
            assert 'requirements' in task['task']
        return httpx.Response(200,json=result(payload))
    monkeypatch.setattr(generation.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    q,tokens=asyncio.run(generation.generate_one({'type':'choice','points':5},{'difficulty':'基础巩固'},[{'document_id':'doc','page':1}],[]))
    assert [c.get('stage','generation') for c in calls]==['generation','generation','blind_review','consistency_review']
    assert calls[1]['validation_feedback']['code']=='QUESTION_LOCAL_CHECK'
    assert q._review['local_checks']['arithmetic']==1 and tokens==400


def test_unrepairable_local_error_respects_attempt_cap(client,setup,monkeypatch):
    calls=[];original=httpx.AsyncClient
    def handler(req):
        task=json.loads(json.loads(req.content)['messages'][1]['content']);calls.append(task)
        assert 'stage' not in task
        return httpx.Response(200,json=result({**valid_payload(),'explanation':'$1+1=3$'}))
    monkeypatch.setattr(generation.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(generation.GenerationError) as error:
        asyncio.run(generation.generate_one({'type':'choice','points':5},{'difficulty':'基础巩固','max_attempts':1},[{'document_id':'doc','page':1}],[]))
    assert len(calls)==1 and error.value.tokens==100


def test_true_false_disagreement_stops_before_consistency_request():
    calls=[]
    async def call(messages):
        calls.append(json.loads(messages[1]['content']))
        payload=blind();payload.update(answer='错误',option_judgments=[])
        return result(payload)
    with pytest.raises(quality.ReviewError,match='判断题'):
        asyncio.run(quality.review_question(call,question(answer='正确',options=[]),'true_false',[],[],{}))
    assert len(calls)==1



def test_proof_by_contradiction_is_not_rejected_by_context_free_arithmetic():
    q=question(explanation='暂定一个假设，经过若干步骤。推导得到 $1=0$。因此原命题成立。')
    assert local_quality.check(q,'proof')['scope']=='proof_not_checked'
    q.explanation='计算后得到 $1=0$。这与已知条件矛盾，因此排除该情况。'
    assert local_quality.check(q,'calculation')['arithmetic']==0


def test_bad_expanded_explanation_is_stopped_before_extra_review(client,setup,monkeypatch):
    from tests.test_api import fake_generate, exam_config
    monkeypatch.setattr(generation,'generate_one',fake_generate)
    eid=client.post('/api/exams',json=exam_config(setup,1)).json()['id']
    before=client.get('/api/exams/'+eid).json()
    q=before['questions'][0];calls=[];original=httpx.AsyncClient
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json=result({'explanation':r'计算得到 $0.4\times0.5=0.3$。'}))
    monkeypatch.setattr(generation.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    response=client.post('/api/questions/'+q['id']+'/explanation')
    assert response.status_code==422 and '本地核验' in response.text
    after=client.get('/api/exams/'+eid).json()
    assert len(calls)==1 and after['tokens']==before['tokens']+100
    assert after['questions'][0]['explanation']==q['explanation']
