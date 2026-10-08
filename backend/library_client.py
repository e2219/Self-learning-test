"""Authenticated, session-scoped bridge from the personal app to a shared library."""
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db, security, share

router = APIRouter(prefix='/api/library', dependencies=[Depends(security.require_auth)])
LIMIT = 3 * 1024 * 1024
COOKIE = 'zhixi_library_session'


def session_key(request):
    return hashlib.sha256(request.cookies.get('study_session', '').encode()).hexdigest()


def normalize_server(value):
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or any(c.isspace() for c in value) or '\\' in value):
            raise ValueError()
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError()
        host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
        return f'{parsed.scheme}://{host}' + (f':{port}' if port and (parsed.scheme, port) not in (('https', 443), ('http', 80)) else '')
    except ValueError:
        raise HTTPException(422, '请输入共享服务器的 HTTPS 网址，不含路径或密码；本机测试可用 http://127.0.0.1:8001。')


def connection(request):
    row = db.one('SELECT server,token FROM library_connections WHERE session_hash=?', (session_key(request),))
    if not row:
        raise HTTPException(409, '请先连接共享学习库服务器。')
    return row


async def remote(server, token, method, path, body=None, query=''):
    # No browser cookies, local API keys, proxy credentials, or redirect following.
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            headers = {'Cookie': f'{COOKIE}={token}'} if token else {}
            async with client.stream(method, server+'/api/'+path, params=query, json=body, headers=headers) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > LIMIT:
                        raise HTTPException(502, '共享服务器返回内容过大。')
                    chunks.append(chunk)
                try:
                    data = json.loads(b''.join(chunks))
                except (ValueError, UnicodeError):
                    raise HTTPException(502, '共享服务器响应无效，请核对服务器地址和版本。')
                if response.status_code >= 300:
                    detail = data.get('detail') if isinstance(data, dict) else None
                    status = 424 if response.status_code == 401 else response.status_code
                    raise HTTPException(status, detail if isinstance(detail, str) and len(detail) < 500 else '共享学习库请求失败。')
                new_token = response.cookies.get(COOKIE)
                return data, new_token
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, '无法连接共享服务器，请检查服务器地址、网络或服务状态；可稍后重试。') from exc


class ConnectionInput(BaseModel):
    server: str = Field(max_length=500)


@router.get('/connection')
def get_connection(request: Request):
    row = db.one('SELECT server FROM library_connections WHERE session_hash=?', (session_key(request),))
    return {'server': row['server'] if row else os.environ.get('LIBRARY_SERVER_URL', ''), 'connected': bool(row)}


@router.put('/connection')
async def set_connection(payload: ConnectionInput, request: Request):
    server = normalize_server(payload.server)
    health, _ = await remote(server, '', 'GET', 'health')
    if not isinstance(health, dict) or health.get('service') != 'shared-library' or health.get('integration_version', 0) < 1:
        raise HTTPException(422, '此地址不是兼容的共享学习库服务，请更新共享服务器到最新版。')
    db.execute("INSERT INTO library_connections VALUES (?,?,'') ON CONFLICT(session_hash) DO UPDATE SET token=CASE WHEN server=excluded.server THEN token ELSE '' END,server=excluded.server", (session_key(request), server))
    return {'server': server, 'connected': True}


ALLOWED = {
    'GET': r'(me|libraries|libraries/[a-f0-9]{32}(?:/posts)?|posts/[a-f0-9]{64}(?:/download)?)',
    'POST': r'(register|login|logout|packs/preview|libraries|libraries/join|libraries/[a-f0-9]{32}/(?:posts|invite))',
    'PUT': r'(password|libraries/[a-f0-9]{32}/(?:access-password|members/[a-f0-9]{32})|posts/[a-f0-9]{64}(?:/favorite)?)',
    'DELETE': r'posts/[a-f0-9]{64}',
}


@router.api_route('/remote/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
async def proxy(path: str, request: Request):
    if not re.fullmatch(ALLOWED[request.method], path):
        raise HTTPException(404, '共享接口不存在。')
    config = connection(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > LIMIT:
            raise HTTPException(413, '试卷包请控制在 2 MB 内。')
    try:
        payload = json.loads(body) if body else None
    except ValueError:
        raise HTTPException(422, '请求格式不正确。')
    result, token = await remote(config['server'], config['token'], request.method, path, payload, request.url.query)
    if path in ('login', 'logout', 'password'):
        db.execute('UPDATE library_connections SET token=? WHERE session_hash=? AND server=?',
                   (token or '', session_key(request), config['server']))
    headers = {'Content-Disposition': 'attachment; filename="zhixi-exam.json"'} if path.endswith('/download') else {}
    return JSONResponse(result, headers=headers)


class ImportInput(BaseModel):
    post_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    revision: int = Field(ge=1)
    course_id: str = Field(default='', max_length=64)
    new_copy: bool = False
    submission_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')


@router.post('/imports')
async def import_shared(payload: ImportInput, request: Request):
    config = connection(request)
    post, _ = await remote(config['server'], config['token'], 'GET', 'posts/'+payload.post_id, query=f'revision={payload.revision}')
    try:
        pack = share.StudyPack.model_validate(post['pack'])
        source = {'server': config['server'], 'library_id': post['library_id'], 'post_id': payload.post_id,
                  'author': post['author'], 'library_name': post.get('library_name', ''), 'revision': payload.revision}
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, '共享试卷格式不完整，请联系发布者修订。')
    origin_key = hashlib.sha256(f"{config['server']}:{payload.post_id}:{payload.revision}".encode()).hexdigest()
    key = ('copy:'+session_key(request)+':'+payload.submission_id) if payload.new_copy else 'source:'+origin_key
    exam_id = share.import_pack(pack, payload.course_id or None, source, key)
    return {'id': exam_id}


@router.get('/import-status/{post_id}')
async def import_status(post_id: str, request: Request):
    if not re.fullmatch(r'[a-f0-9]{64}', post_id):
        raise HTTPException(422, '发布编号无效。')
    config = connection(request)
    post, _ = await remote(config['server'], config['token'], 'GET', 'posts/'+post_id)
    copies = []
    for row in db.rows('SELECT id,config FROM exams'):
        source = json.loads(row['config']).get('shared_source', {})
        if source.get('server') == config['server'] and source.get('post_id') == post_id:
            copies.append({'id': row['id'], 'revision': source['revision']})
    return {'revision': post['revision'], 'copies': copies}
