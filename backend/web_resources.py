"""Bounded Wikimedia search and revision-pinned, attributed text imports.
No arbitrary URL fetches, credentials, scraping login walls or model calls.
"""
import hashlib
import json
import re
import uuid
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from . import db, deepseek
from .models import QuestionEdit

Site = Literal['zh', 'en']
SITES = {'zh': 'https://zh.wikiversity.org', 'en': 'https://en.wikiversity.org'}
LICENSES = {f'https://creativecommons.org/licenses/by-sa/{v}/': f'CC BY-SA {v}' for v in ('3.0', '4.0')}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
        if self.skip: return
        if tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3'): self.parts.append('\n')
        if tag in ('td', 'th'): self.parts.append(' | ')
        if tag == 'img':
            values = dict(attrs)
            if 'mwe-math-fallback-image' in values.get('class', ''):
                self.parts.append('$' + values.get('alt', '') + '$')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip: self.skip -= 1

    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def plain(text):
    parser = PlainText(); parser.feed(text)
    return re.sub(r'\n\s*\n+', '\n\n', ''.join(parser.parts)).strip()


async def request(site, params):
    try:
        async with deepseek.create_client(timeout=httpx.Timeout(25, connect=10), follow_redirects=False) as client:
            response = await client.get(SITES[site] + '/w/api.php', params={
                'format': 'json', 'formatversion': 2, 'maxlag': 5, **params},
                headers={'User-Agent': 'ZhixiStudy/1.0 (https://github.com/e2219/Self-learning-test)'})
        response.raise_for_status()
        if len(response.content) > 2_000_000: raise ValueError()
        data = response.json()
        if not isinstance(data, dict) or 'error' in data: raise ValueError()
        return data
    except (httpx.HTTPError, ValueError, deepseek.ClientSetupError) as exc:
        raise HTTPException(502, '教育资源网站暂不可用，请检查网络或稍后重试；未调用 AI。') from exc


async def search(site, query):
    data = await request(site, {'action': 'query', 'list': 'search', 'srsearch': query,
                                'srnamespace': 0, 'srlimit': 10})
    return [{'page_id': item['pageid'], 'title': item['title'], 'snippet': plain(item.get('snippet', '')),
             'url': SITES[site] + '/wiki/' + quote(item['title'].replace(' ', '_'), safe=''),
             'site': site} for item in data.get('query', {}).get('search', [])]


async def preview(site, page_id):
    data = await request(site, {'action': 'query', 'pageids': page_id, 'prop': 'revisions',
        'rvprop': 'ids|content', 'rvslots': 'main', 'meta': 'siteinfo', 'siprop': 'rightsinfo'})
    query = data.get('query', {})
    pages = query.get('pages', [])
    if not pages or pages[0].get('missing') or pages[0].get('ns') != 0:
        raise HTTPException(422, '只能预览公开的学习资源正文页面。')
    page = pages[0]
    revisions = page.get('revisions', [])
    if not revisions: raise HTTPException(422, '页面版本不可用。')
    revision = revisions[0]
    raw = revision.get('slots', {}).get('main', {}).get('content', '')
    rights_url = query.get('rightsinfo', {}).get('url', '').replace('http://', 'https://').rstrip('/') + '/'
    rights_url = re.sub(r'/deed\.[A-Za-z-]+/$', '/', rights_url)
    license_name = LICENSES.get(rights_url)
    parsed = await request(site, {'action': 'parse', 'oldid': revision['revid'], 'prop': 'text', 'disableeditsection': 1})
    rendered = parsed.get('parse', {}).get('text', '')
    if not isinstance(rendered, str): raise HTTPException(502, '来源页面格式异常。')
    text = plain(rendered)
    # Site-wide text licenses do not cover copyright exceptions, quoted works, media or transclusions.
    # Fail closed for ambiguous pages; search links remain usable.
    ambiguous = bool(re.search(r'all rights reserved|fair[ _-]?use|copyright violation|copyvio|版权所有|保留所有权利|合理使用|侵权|<blockquote|\{\{\s*(?:quote|quotation|摘录)|\{\{\s*:|<img(?![^>]*mwe-math-fallback-image)', raw + '\n' + rendered, re.I))
    allowed = bool(license_name and text and not ambiguous and len(text) <= 100_000)
    base = SITES[site]
    value = {'id': uuid.uuid4().hex, 'title': page['title'], 'text': text[:100_000],
        'url': base + '/w/index.php?oldid=' + str(revision['revid']),
        'authors_url': base + '/w/index.php?title=' + quote(page['title'], safe='') + '&action=history',
        'license': license_name or '许可未确认', 'license_url': rights_url if license_name else '',
        'revision': revision['revid'], 'importable': allowed,
        'reason': '' if allowed else '未确认文本许可，或页面包含图片、引用/许可例外等需要单独核对的内容；本页仅提供来源链接。'}
    if allowed:
        db.execute('INSERT INTO web_sources(id,data) VALUES (?,?)', (value['id'], db.dump(value)))
    else:
        value['text'] = ''
    return value


class ImportInput(BaseModel):
    source_id: str = Field(max_length=64)
    course_id: str = Field(max_length=64)
    target_exam_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=100)
    question_type: Literal['choice', 'multiple_choice', 'indefinite_choice', 'true_false', 'fill', 'calculation', 'proof']
    question: QuestionEdit
    confirmed_license: bool = False
    submission_id: str = Field(min_length=8, max_length=100)


def import_question(payload):
    from .generation import validate_content, GenerationError
    row = db.one('SELECT data FROM web_sources WHERE id=?', (payload.source_id,))
    if not row: raise HTTPException(404, '来源预览已失效，请重新检索。')
    source = json.loads(row['data'])
    if not source['importable'] or not payload.confirmed_license:
        raise HTTPException(422, '只有许可已确认、且无已知例外的正文摘录可导入。')
    if not db.one('SELECT id FROM courses WHERE id=?', (payload.course_id,)):
        raise HTTPException(404, '课程不存在。')
    q = payload.question.model_dump()
    # User chooses a verbatim exercise, not a model-generated reconstruction.
    compact = lambda s: re.sub(r'\s+|\[\[blank:\d+\]\]|_{2,}', '', s)
    if not compact(q['stem']) or any(compact(part) not in compact(source['text']) for part in [q['stem'], *q['options']]):
        raise HTTPException(422, '题干和选项须摘自当前来源正文。请勿粘贴其他网站内容；导入后可在题目编辑中修订。')
    citation = {'document_id': 'web:' + source['id'], 'page': 1, 'name': source['title']}
    q['sources'] = [citation]
    try: checked = validate_content(q, payload.question_type, [citation], [])
    except GenerationError as exc: raise HTTPException(422, str(exc)) from exc
    public_source = {k: source[k] for k in ('url', 'authors_url', 'license', 'license_url', 'revision')}
    citation.update(public_source)
    citation['imported'] = True
    key = 'web:' + payload.submission_id
    digest = hashlib.sha256(db.dump(payload.model_dump()).encode()).hexdigest()
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT * FROM exam_submissions WHERE key=?', (key,)).fetchone()
        if old:
            if old['request_hash'] != digest: raise HTTPException(409, '提交标识已使用，请重新打开导入表单。')
            if not con.execute('SELECT id FROM exams WHERE id=?', (old['exam_id'],)).fetchone(): raise HTTPException(410, '试卷已删除，不会重复创建。')
            return old['exam_id']
        exam_id = payload.target_exam_id or uuid.uuid4().hex
        if payload.target_exam_id:
            target = con.execute('SELECT * FROM exams WHERE id=?', (exam_id,)).fetchone()
            if not target or target['course_id'] != payload.course_id or target['status'] != 'ready' or json.loads(target['config']).get('origin') != 'web_import':
                raise HTTPException(422, '只能追加到同课程、已就绪的来源摘录试卷。')
        position = con.execute('SELECT coalesce(max(position),0)+1 FROM questions WHERE exam_id=?', (exam_id,)).fetchone()[0]
        if position > 100: raise HTTPException(422, '一份摘录试卷最多 100 题，请另建试卷。')
        config = {'origin': 'web_import', 'ranges': [], 'duration': 60, 'difficulty': '来源摘录', 'rules': [], 'focus': '', 'mode': 'custom', 'course_id': payload.course_id, 'title':payload.title}
        if not payload.target_exam_id: con.execute("INSERT INTO exams(id,course_id,title,config,status) VALUES (?,?,?,?,'ready')", (exam_id,payload.course_id,payload.title,db.dump(config)))
        con.execute("""INSERT INTO questions(id,exam_id,position,type,points,status,stem,options,answer,explanation,knowledge,sources,blanks,review)
            VALUES (?,?,?,?,?,'ready',?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex,exam_id,position,payload.question_type,q['points'],checked.stem,db.dump(checked.options),checked.answer,checked.explanation,checked.knowledge,db.dump([citation]),db.dump([b.model_dump() for b in checked.blanks]),db.dump({'method':'web_import'})))
        con.execute('INSERT INTO exam_submissions(key,request_hash,exam_id) VALUES (?,?,?)', (key,digest,exam_id))
    return exam_id
