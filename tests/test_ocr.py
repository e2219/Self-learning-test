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
        assert request.headers['authorization'] == 'Bearer test-key-never-send'
        assert body['messages'][0]['role'] == 'user'
        assert body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'text': TEXT})}}], 'usage': {'total_tokens': 321}})
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
