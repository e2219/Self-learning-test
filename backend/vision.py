"""Bounded source images for direct generation and original-page review.

Only local, validated document IDs are accepted. Encoded images never enter drafts,
usage records, or persisted question candidates.
"""
import base64
import json
from starlette.concurrency import run_in_threadpool
from . import db, ocr, materials

MAX_DIRECT_PAGES = 4


def references(config):
    result, seen = [], set()
    for scope in config['ranges']:
        doc = db.one('SELECT * FROM documents WHERE id=?', (scope['document_id'],))
        if not doc or doc['course_id'] != config['course_id'] or not 1 <= scope['start'] <= scope['end'] <= doc['page_count']:
            raise ValueError('图片资料不属于此课程，或页码无效。')
        for number in range(scope['start'], scope['end'] + 1):
            key = (doc['id'], number)
            if key in seen: continue
            seen.add(key)
            if len(seen) > MAX_DIRECT_PAGES:
                raise ValueError('看图仿题每次最多 4 页，请缩小范围。')
            result.append({'document_id':doc['id'], 'page':number, 'name':doc['name'], 'kind':doc['kind'],
                'role':scope.get('role') if scope.get('role', 'auto') != 'auto' else ('reference' if doc['kind'] == '往年试卷' else 'knowledge'),
                'text':'直接参考原图（未转写）', 'visual':True})
    if not result: raise ValueError('请先选择图片或 PDF 页面。')
    return result


def review_sources(refs, *, uncertain_only=False):
    result, seen = [], set()
    for ref in refs:
        key = (ref['document_id'], ref['page'])
        if key in seen: continue
        seen.add(key)
        page = db.one('SELECT text,ocr_done,table_flag FROM pages WHERE document_id=? AND number=?', key)
        text = ref.get('text','') + '\n' + (page['text'] if page else '')
        uncertain = any(mark in text for mark in ('[无法辨认]', '[图形未转写]', '[表格待核对]'))
        table = materials.table_info(text, flagged=bool(page and page['table_flag']))['has_table']
        if ref.get('visual') or table or uncertain or (not uncertain_only and page and page['ocr_done']):
            result.append(ref)
    return result


async def with_images(messages, refs):
    blocks = [{'type':'text', 'text':messages[-1]['content']}]
    for ref in refs:
        data = await run_in_threadpool(ocr.render_page, db.DATA_DIR / 'uploads' / f"{ref['document_id']}.pdf", ref['page'])
        blocks.extend([{'type':'text', 'text':json.dumps({'document_id':ref['document_id'], 'page':ref['page']},ensure_ascii=False)},
            {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,' + base64.b64encode(data).decode(), 'detail':'original'}}])
    return [*messages[:-1], {**messages[-1], 'content':blocks}]
