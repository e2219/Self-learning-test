import asyncio
import io
import json

import httpx
import pytest
from pypdf import PdfWriter

from backend import db, ocr
from tests.test_api import client, setup, exam_config  # noqa: F401

TEXT = r"独立事件的乘法公式：若事件 A 和 B 相互独立，则 $P(A\cap B)=P(A)P(B)$。这与互斥事件不同。"


def blank_doc(client, course, count=2):
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=595, height=842)
    output = io.BytesIO()
    writer.write(output)
    return client.post(f"/api/courses/{course['id']}/documents", files={"file": ("scan.pdf", output.getvalue())}).json()


async def recognize(image):
    assert image.startswith(b'\xff\xd8')
    return ocr.OCRResult(text=TEXT), 42


def test_ocr_to_retrieval_and_cache(client, setup, monkeypatch):
    course, _ = setup
    doc = blank_doc(client, course)
    doc_id = doc['id']
    monkeypatch.setattr(ocr, 'recognize_page', recognize)
    response = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 2})
    assert response.status_code == 201
    job = client.get(f"/api/ocr/{response.json()['id']}").json()
    assert job['status'] == 'ready' and job['tokens'] == 84
    assert [p['status'] for p in job['pages']] == ['ready', 'ready']
    assert client.get(f'/api/documents/{doc_id}/pages/1').json()['text'] == TEXT
    docs = client.get(f"/api/courses/{course['id']}/documents").json()
    assert next(d for d in docs if d['id'] == doc_id)['usable_pages'] == 2
    config = exam_config((course, doc))
    assert client.post('/api/retrieval-preview', json=config).status_code == 200
    response = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 2})
    cached = client.get(f"/api/ocr/{response.json()['id']}").json()
    assert cached['tokens'] == 0
    assert all(p['status'] == 'skipped' for p in cached['pages'])
    assert client.get(f'/api/documents/{doc_id}/pages/1/image').headers['content-type'] == 'image/jpeg'
    assert client.get(f'/api/documents/{doc_id}/pages/3/image').status_code == 404


def test_failure_retry_and_restart_preserve_completed(client, setup, monkeypatch):
    course, _ = setup
    doc = blank_doc(client, course)
    calls = []
    async def flaky(image):
        calls.append(1)
        if len(calls) == 2:
            raise ocr.OCRError('测试超时')
        return await recognize(image)
    monkeypatch.setattr(ocr, 'recognize_page', flaky)
    job_id = client.post(f"/api/documents/{doc['id']}/ocr", json={'start': 1, 'end': 2}).json()['id']
    assert client.get(f'/api/ocr/{job_id}').json()['status'] == 'partial'
    before = client.get(f"/api/documents/{doc['id']}/pages/1").json()
    db.execute("UPDATE ocr_jobs SET status='running' WHERE id=?", (job_id,))
    db.execute("UPDATE ocr_job_pages SET status='running' WHERE job_id=? AND number=2", (job_id,))
    db.init_db()
    assert client.get(f'/api/ocr/{job_id}').json()['status'] == 'partial'
    client.post(f'/api/ocr/{job_id}/retry')
    job = client.get(f'/api/ocr/{job_id}').json()
    assert job['status'] == 'ready' and job['tokens'] == 84 and len(calls) == 3
    assert client.get(f"/api/documents/{doc['id']}/pages/1").json() == before


def test_manual_edit_during_ocr_is_never_overwritten(client, setup, monkeypatch):
    course, doc = setup
    async def concurrent_edit(image):
        db.execute("UPDATE pages SET text='人工修正版',edited=1 WHERE document_id=? AND number=1", (doc['id'],))
        return await recognize(image)
    monkeypatch.setattr(ocr, 'recognize_page', concurrent_edit)
    job_id = client.post(f"/api/documents/{doc['id']}/ocr", json={'start': 1, 'end': 1, 'force': True}).json()['id']
    assert client.get(f'/api/ocr/{job_id}').json()['pages'][0]['status'] == 'skipped'
    assert client.get(f"/api/documents/{doc['id']}/pages/1").json()['text'] == '人工修正版'
    async def never(image):
        pytest.fail('Must not send manually corrected page')
    monkeypatch.setattr(ocr, 'recognize_page', never)
    client.post(f"/api/documents/{doc['id']}/ocr", json={'start': 1, 'end': 1, 'force': True})


def test_cancel_finishes_current_page_and_protects_delete(client, setup, monkeypatch):
    course, _ = setup
    doc = blank_doc(client, course)
    async def cancel(image):
        job = db.one("SELECT * FROM ocr_jobs WHERE document_id=?", (doc['id'],))
        assert ocr.is_busy(doc['id'])
        db.execute("UPDATE ocr_jobs SET status='cancelling' WHERE id=?", (job['id'],))
        return await recognize(image)
    monkeypatch.setattr(ocr, 'recognize_page', cancel)
    job_id = client.post(f"/api/documents/{doc['id']}/ocr", json={'start': 1, 'end': 2}).json()['id']
    job = client.get(f'/api/ocr/{job_id}').json()
    assert job['status'] == 'cancelled'
    assert [p['status'] for p in job['pages']] == ['ready', 'pending']
    db.execute("UPDATE ocr_jobs SET status='queued' WHERE id=?", (job_id,))
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 409
    assert client.delete(f"/api/courses/{course['id']}").status_code == 409
    assert client.post(f"/api/documents/{doc['id']}/ocr", json={'start': 1, 'end': 1}).status_code == 409
    assert client.post(f'/api/ocr/{job_id}/retry').status_code == 409
    assert client.post(f'/api/ocr/{job_id}/cancel').json()['status'] == 'cancelling'


def test_ocr_bounds_auth_and_key(client, setup):
    doc = blank_doc(client, setup[0], count=21)
    path = f"/api/documents/{doc['id']}/ocr"
    for start, end in [(0, 1), (2, 1), (1, 22), (1, 21)]:
        assert client.post(path, json={'start': start, 'end': end}).status_code == 422
    assert client.get(path).json() is None
    db.set_setting('api_key', '')
    assert client.post(path, json={'start': 1, 'end': 1}).status_code == 422
    client.post('/api/logout')
    assert client.post(path, json={'start': 1, 'end': 1}).status_code == 401
    assert client.get(f"/api/documents/{doc['id']}/pages/1/image").status_code == 401


def test_vision_adapter_payload(client, setup, monkeypatch):
    original = httpx.AsyncClient
    def handler(request):
        body = json.loads(request.content)
        assert body['model'] == 'deepseek-flash'
        assert 'response_format' not in body
        assert ocr.TEXT_END in body['messages'][0]['content'][0]['text']
        assert request.headers['authorization'] == 'Bearer test-key-never-send'
        assert body['messages'][0]['role'] == 'user'
        assert body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': ocr.TEXT_START + '\n' + TEXT + '\n' + ocr.TEXT_END}}], 'usage': {'total_tokens': 321}})
    monkeypatch.setattr(ocr.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result, tokens = asyncio.run(ocr.recognize_page(b'fake-image'))
    assert result.text == TEXT and tokens == 321


@pytest.mark.parametrize('status,finish', [(401, 'stop'), (402, 'stop'), (429, 'stop'), (200, 'length'), (200, 'stop')])
def test_provider_errors_do_not_leak_or_overwrite(client, setup, monkeypatch, status, finish):
    original = httpx.AsyncClient
    def handler(request):
        return httpx.Response(status, json={'secret': 'DO-NOT-LEAK', 'choices': [{'finish_reason': finish, 'message': {'content': 'DO-NOT-LEAK'}}]})
    monkeypatch.setattr(ocr.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    doc_id = setup[1]['id']
    before = client.get(f'/api/documents/{doc_id}/pages/1').json()
    job_id = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 1, 'force': True}).json()['id']
    response = client.get(f'/api/ocr/{job_id}')
    assert response.json()['status'] == 'partial'
    assert 'DO-NOT-LEAK' not in response.text
    assert client.get(f'/api/documents/{doc_id}/pages/1').json() == before

# Formula-heavy transcriptions must never pass through a second JSON decoder.
MATH_PAGE = r'''# 事件运算及概率
设 $A, B$ 为事件，则 $A\cup B$ 是并事件，$A\cap B$ 是交事件。
$$P(A\cup B)=P(A)+P(B)-P(A\cap B)$$
$$\frac{1}{\sqrt{2\pi}}\int_{-\infty}^{+\infty}e^{-x^2/2}\,dx=1$$
$$\begin{pmatrix}a&b\\c&d\end{pmatrix},\quad\sum_{i=1}^{n}i=\frac{n(n+1)}2$$
注意 $\theta,\nu,\rho,\beta$ 和 $\text{事件 A}$；引号 "成立" 保持不变。
[图形未转写]，某处 [无法辨认]。'''


def response_body(text=MATH_PAGE, **patch):
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': ocr.TEXT_START + '\n' + text + '\n' + ocr.TEXT_END}}], 'usage': {'total_tokens': 789}, **patch}


def test_latex_json_failure_reproduced_and_plain_transcription_preserved():
    from pydantic import ValidationError
    # Reproduces the previous strict JSON failure from a single LaTeX backslash.
    with pytest.raises(ValidationError):
        ocr.OCRResult.model_validate_json(r'{"text":"$A\cup B$"}')
    # Worse: JSON-valid escape sequences silently corrupted math in the old code.
    corrupted = ocr.OCRResult.model_validate_json(r'{"text":"$\frac{1}{2}$"}')
    assert '\x0c' in corrupted.text
    result, tokens = ocr.decode_response(response_body())
    assert result.text == MATH_PAGE and tokens == 789
    assert '\x0c' not in result.text and r'\frac' in result.text and r'\\c' in result.text


@pytest.mark.parametrize('usage', [None, {}, {'total_tokens': None}, {'total_tokens': -1}, {'total_tokens': True}, {'total_tokens': 'unknown'}])
def test_usage_metadata_cannot_break_successful_transcription(usage):
    result, tokens = ocr.decode_response(response_body(usage=usage))
    assert result.text == MATH_PAGE and tokens == 0


@pytest.mark.parametrize('data,code', [
    (None, 'OCR_RESPONSE_SHAPE'),
    ({'choices': []}, 'OCR_RESPONSE_SHAPE'),
    ({'choices': [None]}, 'OCR_RESPONSE_SHAPE'),
    ({'choices': [{'finish_reason': 'length'}]}, 'OCR_TRUNCATED'),
    ({'choices': [{'finish_reason': 'content_filter'}]}, 'OCR_INCOMPLETE'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'content': None}}]}, 'OCR_EMPTY_CONTENT'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'content': ['bad']}}]}, 'OCR_EMPTY_CONTENT'),
])
def test_provider_failure_categories(data, code):
    with pytest.raises(ocr.OCRError, match=code):
        ocr.decode_response(data)


@pytest.mark.parametrize('text,code', [
    (ocr.TEXT_START + '\npartial', 'OCR_TEXT_BOUNDARY'),
    ('unmarked response', 'OCR_TEXT_BOUNDARY'),
    (ocr.TEXT_START + '\n' + ocr.TEXT_END, 'OCR_EMPTY_TEXT'),
    (ocr.TEXT_START + ocr.TEXT_START + ocr.TEXT_END, 'OCR_TEXT_BOUNDARY'),
    (ocr.TEXT_START + '\x0crac' + ocr.TEXT_END, 'OCR_TEXT_CONTROL'),
    (ocr.TEXT_START + 'x' * 50001 + ocr.TEXT_END, 'OCR_TEXT_LIMIT'),
])
def test_incomplete_or_invalid_transcriptions_are_not_silently_saved(text, code):
    with pytest.raises(ocr.OCRError, match=code):
        ocr.parse_transcription(text)


def test_explicit_blank_page_is_distinct_from_empty_response():
    result, tokens = ocr.decode_response(response_body(ocr.BLANK_PAGE))
    assert result.text == '' and tokens == 789


def test_format_failure_keeps_usage_and_never_logs_content(client, setup, monkeypatch, caplog):
    original = httpx.AsyncClient
    doc_id = setup[1]['id']
    before = client.get(f'/api/documents/{doc_id}/pages/1').json()
    body = response_body()
    body['choices'][0]['message']['content'] = 'PRIVATE-PAGE-DO-NOT-LOG'
    monkeypatch.setattr(ocr.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)), **kw))
    job_id = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 1, 'force': True}).json()['id']
    job = client.get(f'/api/ocr/{job_id}').json()
    assert job['tokens'] == 789 and job['status'] == 'partial'
    assert 'OCR_TEXT_BOUNDARY' in job['pages'][0]['error']
    assert 'OCR_TEXT_BOUNDARY' in caplog.text and 'PRIVATE-PAGE-DO-NOT-LOG' not in caplog.text
    assert client.get(f'/api/documents/{doc_id}/pages/1').json() == before
    body['choices'][0]['message']['content'] = response_body()['choices'][0]['message']['content']
    client.post(f'/api/ocr/{job_id}/retry')
    job = client.get(f'/api/ocr/{job_id}').json()
    assert job['tokens'] == 1578 and job['status'] == 'ready'
    assert client.get(f'/api/documents/{doc_id}/pages/1').json()['text'] == MATH_PAGE


def test_non_json_http_response_is_distinguished(client, setup, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(ocr.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda _: httpx.Response(200, text='<html>PRIVATE PROXY ERROR</html>')), **kw))
    with pytest.raises(ocr.OCRError, match='OCR_RESPONSE_JSON') as error:
        asyncio.run(ocr.recognize_page(b'test-image'))
    assert 'PRIVATE' not in str(error.value)

@pytest.mark.parametrize('fence', ['```', '```markdown', '```md', '```text'])
def test_optional_outer_code_fence_does_not_change_latex(fence):
    wrapped = fence + '\n' + ocr.TEXT_START + '\n' + MATH_PAGE + '\n' + ocr.TEXT_END + '\n```'
    assert ocr.parse_transcription(wrapped).text == MATH_PAGE
    with pytest.raises(ocr.OCRError, match='OCR_TEXT_BOUNDARY'):
        ocr.parse_transcription(fence + '\n' + MATH_PAGE + '\n```')


def test_proxy_dependency_failure_happens_before_request_and_is_clear(client, setup, monkeypatch, caplog):
    def missing(**kwargs):
        raise ImportError('Using SOCKS proxy but socksio missing; PRIVATE-CREDENTIAL')
    monkeypatch.setattr(ocr.httpx, 'AsyncClient', missing)
    doc_id = setup[1]['id']
    job_id = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 1, 'force': True}).json()['id']
    job = client.get(f'/api/ocr/{job_id}').json()
    item = job['pages'][0]
    assert job['tokens'] == 0 and item['stage'] == 'client_setup' and item['http_status'] is None
    assert 'DEEPSEEK_PROXY_DEPENDENCY' in item['error'] and '尚未发出' in item['error']
    assert 'PRIVATE-CREDENTIAL' not in str(job) + caplog.text


def test_http_response_stage_survives_failed_decode(client, setup, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(ocr.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda _: httpx.Response(401, text='PRIVATE')), **kw))
    doc_id = setup[1]['id']
    job_id = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 1, 'force': True}).json()['id']
    item = client.get(f'/api/ocr/{job_id}').json()['pages'][0]
    assert item['stage'] == 'response_received' and item['http_status'] == 401


def test_unexpected_error_reports_type_stage_without_raw_message(client, setup, monkeypatch, caplog):
    async def fail(image):
        raise RuntimeError('PRIVATE-API-KEY-IN-ERROR')
    monkeypatch.setattr(ocr, 'recognize_page', fail)
    doc_id = setup[1]['id']
    job_id = client.post(f'/api/documents/{doc_id}/ocr', json={'start': 1, 'end': 1, 'force': True}).json()['id']
    job = client.get(f'/api/ocr/{job_id}').json()
    assert 'OCR_INTERNAL:RuntimeError' in job['pages'][0]['error']
    assert 'PRIVATE-API-KEY-IN-ERROR' not in str(job) + caplog.text
    assert 'RuntimeError' in caplog.text and 'stage=' in caplog.text
