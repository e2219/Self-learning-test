import asyncio
import io

from PIL import Image
import pytest

from backend import db, materials, ocr, generation
from tests.test_api import client, setup, exam_config  # noqa: F401

TABLE = '实验结果，单位 mmol/L\n\n| 组别 | 处理前 | 处理后 |\n| --- | --- | --- |\n| A | 10 | 12 |\n| B | 20 | 22 |\n\n注：温度为 25℃。'


def test_table_gate_preserves_whole_page_and_footnotes():
    page = {'text': TABLE, 'table_reviewed': 0}
    assert materials.page_info(page)['needs_review']
    assert materials.chunks(page) == []
    page['table_reviewed'] = 1
    assert materials.chunks(page) == [TABLE]
    assert materials.table_info(TABLE.replace('| A | 10 | 12 |', '| A | 10 |'))['table_issues']
    assert materials.table_info(TABLE.replace('12', '[无法辨认]'), reviewed=True)['needs_review']


def test_verification_revoked_on_edit_and_stale_confirmation_rejected(client, setup):
    doc = setup[1]['id']; url = f'/api/documents/{doc}/pages/1'
    page = client.put(url, json={'text': TABLE}).json()
    assert page['needs_review']
    assert client.post('/api/retrieval-preview', json=exam_config(setup)).status_code == 422
    verified = client.put(url+'/table-review', json={'text_hash': page['text_hash'], 'confirmed': True})
    assert verified.status_code == 200 and not verified.json()['needs_review']
    refs = client.post('/api/retrieval-preview', json=exam_config(setup)).json()['sources']
    assert refs[0]['text'] == TABLE
    client.put(url, json={'text': TABLE.replace('12', '13')})
    assert client.put(url+'/table-review', json={'text_hash': page['text_hash'], 'confirmed': True}).status_code == 409
    assert client.get(url).json()['needs_review']


def test_malformed_table_cannot_be_confirmed(client, setup):
    url = f"/api/documents/{setup[1]['id']}/pages/1"
    page = client.put(url, json={'text': TABLE.replace('| A | 10 | 12 |', '| A | 10 |')}).json()
    assert client.put(url+'/table-review', json={'text_hash': page['text_hash'], 'confirmed': True}).status_code == 422


def test_region_ocr_returns_draft_without_changing_page(client, setup, monkeypatch):
    url = f"/api/documents/{setup[1]['id']}/pages/1"
    before = client.get(url).json()
    async def fake(image): return ocr.OCRResult(text=TABLE), 77
    monkeypatch.setattr(ocr, 'recognize_page', fake)
    response = client.post(url+'/recognize-region', json={'x': 0, 'y': 0, 'width': 1, 'height': .5})
    assert response.status_code == 200 and response.json()['tokens'] == 77
    assert client.get(url).json() == before
    assert client.post(url+'/recognize-region', json={'x': .8, 'y': 0, 'width': .5, 'height': 1}).status_code == 422


def test_crop_render_is_bounded_and_uses_selected_aspect(client, setup):
    path = db.DATA_DIR/'uploads'/f"{setup[1]['id']}.pdf"
    image = Image.open(io.BytesIO(ocr.render_page(path, 1, {'x': 0, 'y': 0, 'width': 1, 'height': .5})))
    assert max(image.size) <= 2401
    assert image.width > image.height


def test_vision_table_structure_checks_are_not_human_confirmation():
    page = {'text': TABLE, 'ocr_done': 1}
    assert materials.chunks(page) == [TABLE]
    page['text'] = TABLE.replace('| A | 10 | 12 |', '| A | 10 |')
    assert materials.page_info(page)['needs_review']
    assert materials.chunks(page) == []
