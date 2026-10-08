"""Small, invite-only sharing service. It never loads personal data or calls a model."""
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..share import StudyPack
from . import store

COOKIE = 'zhixi_library_session'
BODY_LIMIT = 3 * 1024 * 1024


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310_000).hex()


def secure_cookies():
    return os.environ.get('LIBRARY_COOKIE_SECURE', 'true').lower() != 'false'


@asynccontextmanager
async def lifespan(app):
    if secure_cookies() and not os.environ.get('LIBRARY_PUBLIC_ORIGIN', '').startswith('https://'):
        raise RuntimeError('公网运行请设置 https:// 开头的 LIBRARY_PUBLIC_ORIGIN；本机测试可设置 LIBRARY_COOKIE_SECURE=false。')
    store.initialize()
    yield


app = FastAPI(title='知习 · 共享学习库', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def protection(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        expected = os.environ.get('LIBRARY_PUBLIC_ORIGIN') or str(request.base_url).rstrip('/')
        if (origin and origin.rstrip('/') != expected.rstrip('/')) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '不允许跨站请求。'}, 403)
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > BODY_LIMIT:
                return JSONResponse({'detail': '请求过大，试卷包请控制在 2 MB 内。'}, 413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
    response = await call_next(request)
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'same-origin'})
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def rate(key, limit, seconds):
    now = time.time()
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM rate_limits WHERE expires<?', (now,))
        row = con.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
        blocked = row and row['count'] >= limit
        if not blocked:
            con.execute('INSERT INTO rate_limits(key,count,expires) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now + seconds))
    if blocked:
        raise HTTPException(429, '操作过于频繁，请稍后重试。')


def address(request):
    return request.client.host if request.client else 'unknown'


def current_user(request: Request):
    with store.connection() as con:
        row = con.execute('SELECT u.id,u.username,u.nickname FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                          (digest(request.cookies.get(COOKIE, '')), time.time())).fetchone()
    if not row:
        raise HTTPException(401, '请先登录共享学习库。')
    return dict(row)


def membership(con, library_id, user, manage=False):
    lib = con.execute('SELECT * FROM libraries WHERE id=?', (library_id,)).fetchone()
    member = con.execute('SELECT role FROM members WHERE library_id=? AND user_id=?', (library_id, user['id'])).fetchone()
    if not lib or not member or member['role'] == 'removed':
        raise HTTPException(404, '学习库不存在或你尚未加入。')
    role = 'owner' if lib['owner_id'] == user['id'] else member['role']
    if role not in ('owner', 'admin', 'member'):
        raise HTTPException(403, '成员角色无效，请联系创建者。')
    if manage and role not in ('owner', 'admin'):
        raise HTTPException(403, '只有学习库创建者或管理员可以执行此操作。')
    return {**dict(lib), 'role': role}


def access_post(con, post_id, user, edit=False):
    post = con.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
    if not post:
        raise HTTPException(404, '内容不存在。')
    lib = membership(con, post['library_id'], user)
    if edit and post['author_id'] != user['id']:
        raise HTTPException(403, '只有发布者可以修订内容。')
    return post, lib


class Credentials(BaseModel):
    username: str = Field(pattern=r'^[a-zA-Z0-9_]{3,32}$')
    password: str = Field(min_length=10, max_length=128)


class Registration(Credentials):
    nickname: str = Field(min_length=1, max_length=40)
    registration_code: str = Field(default='', max_length=200)


class LibraryInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)


class JoinInput(BaseModel):
    invite_code: str = Field(min_length=8, max_length=100)


class PostInput(BaseModel):
    pack: StudyPack
    note: str = Field(default='', max_length=1000)
    submission_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')


class RevisionInput(BaseModel):
    pack: StudyPack
    note: str = Field(default='', max_length=1000)
    revision: int = Field(ge=1)


class PasswordInput(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@app.get('/api/health')
def health():
    return {'ok': True, 'service': 'shared-library'}


@app.post('/api/register', status_code=201)
def register(payload: Registration, request: Request):
    rate('register:'+address(request), 20, 3600)
    code = os.environ.get('LIBRARY_REGISTRATION_CODE', '')
    if code and not hmac.compare_digest(code.encode(), payload.registration_code.encode()):
        raise HTTPException(403, '站点注册口令不正确。')
    if not payload.nickname.strip():
        raise HTTPException(422, '昵称不能为空。')
    salt = secrets.token_hex(16)
    hashed = password_hash(payload.password, salt)
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM users WHERE username=?', (payload.username.lower(),)).fetchone():
            raise HTTPException(409, '用户名已被使用。')
        if con.execute('SELECT count(*) FROM users').fetchone()[0] >= 2000:
            raise HTTPException(409, '本站注册人数已达上限，请联系管理员。')
        con.execute('INSERT INTO users VALUES (?,?,?,?,?)', (uuid.uuid4().hex, payload.username.lower(), payload.nickname.strip(), salt, hashed))
    return {'ok': True}


@app.post('/api/login')
def login(payload: Credentials, request: Request, response: Response):
    rate('login:'+address(request), 30, 300)
    with store.connection() as con:
        row = con.execute('SELECT * FROM users WHERE username=?', (payload.username.lower(),)).fetchone()
        hashed = password_hash(payload.password, row['salt'] if row else '00'*16)
        if not row or not hmac.compare_digest(hashed, row['password_hash']):
            raise HTTPException(401, '用户名或密码不正确。')
        token = secrets.token_urlsafe(32)
        con.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        con.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), row['id'], time.time()+86400*7))
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=secure_cookies(), max_age=86400*7)
    return {'id': row['id'], 'username': row['username'], 'nickname': row['nickname']}


@app.get('/api/me')
def me(user=Depends(current_user)):
    return user


@app.post('/api/logout')
def logout(request: Request, response: Response):
    with store.connection() as con:
        con.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE, secure=secure_cookies(), httponly=True, samesite='strict')
    return {'ok': True}


@app.put('/api/password')
def change_password(payload: PasswordInput, user=Depends(current_user)):
    rate('password:'+user['id'], 10, 300)
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
        if not hmac.compare_digest(password_hash(payload.old_password, row['salt']), row['password_hash']):
            raise HTTPException(403, '原密码不正确。')
        salt = secrets.token_hex(16)
        con.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt, password_hash(payload.new_password, salt), user['id']))
        con.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
    return {'ok': True}


@app.post('/api/packs/preview')
def preview_pack(pack: StudyPack, user=Depends(current_user)):
    return pack.model_dump()


@app.get('/api/libraries')
def libraries(user=Depends(current_user)):
    with store.connection() as con:
        return [dict(r) for r in con.execute('''SELECT l.id,l.name,l.description,l.owner_id,m.role,
            (SELECT count(*) FROM posts p WHERE p.library_id=l.id) AS post_count
            FROM libraries l JOIN members m ON m.library_id=l.id WHERE m.user_id=? AND m.role!='removed' ORDER BY l.rowid DESC''', (user['id'],))]


@app.post('/api/libraries', status_code=201)
def create_library(payload: LibraryInput, user=Depends(current_user)):
    rate('create-library:'+user['id'], 10, 3600)
    if not payload.name.strip():
        raise HTTPException(422, '学习库名称不能为空。')
    library_id, code = uuid.uuid4().hex, secrets.token_urlsafe(18)
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT count(*) FROM libraries WHERE owner_id=?', (user['id'],)).fetchone()[0] >= 10:
            raise HTTPException(409, '每人最多创建 10 个学习库。')
        con.execute('INSERT INTO libraries VALUES (?,?,?,?,?)', (library_id, payload.name.strip(), payload.description, user['id'], digest(code)))
        con.execute("INSERT INTO members VALUES (?,?,'owner')", (library_id, user['id']))
    return {'id': library_id, 'invite_code': code}


@app.post('/api/libraries/join')
def join(payload: JoinInput, user=Depends(current_user)):
    rate('join:'+user['id'], 15, 300)
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        lib = con.execute('SELECT id FROM libraries WHERE invite_hash=?', (digest(payload.invite_code.strip()),)).fetchone()
        if not lib:
            raise HTTPException(404, '邀请码无效或已更换。')
        prior = con.execute('SELECT role FROM members WHERE library_id=? AND user_id=?', (lib['id'], user['id'])).fetchone()
        if prior and prior['role'] == 'removed':
            raise HTTPException(403, '你已被移出该学习库，请联系管理员恢复成员资格。')
        if not prior and con.execute('SELECT count(*) FROM members WHERE library_id=?', (lib['id'],)).fetchone()[0] >= 200:
            raise HTTPException(409, '学习库最多支持 200 名成员。')
        con.execute("INSERT OR IGNORE INTO members VALUES (?,?,'member')", (lib['id'], user['id']))
    return {'id': lib['id']}


@app.get('/api/libraries/{library_id}')
def library_detail(library_id: str, user=Depends(current_user)):
    with store.connection() as con:
        lib = membership(con, library_id, user)
        members = [dict(r) for r in con.execute('SELECT u.id,u.nickname,m.role FROM members m JOIN users u ON u.id=m.user_id WHERE m.library_id=? ORDER BY m.role,u.nickname', (library_id,))]
        return {'id':lib['id'], 'name':lib['name'], 'description':lib['description'], 'owner_id':lib['owner_id'], 'role':lib['role'], 'members':members}


@app.post('/api/libraries/{library_id}/invite')
def rotate_invite(library_id: str, user=Depends(current_user)):
    code = secrets.token_urlsafe(18)
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        membership(con, library_id, user, manage=True)
        con.execute('UPDATE libraries SET invite_hash=? WHERE id=?', (digest(code), library_id))
    return {'invite_code': code}


@app.put('/api/libraries/{library_id}/members/{member_id}')
def member_role(library_id: str, member_id: str, role: Literal['admin','member','removed'], user=Depends(current_user)):
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        lib = membership(con, library_id, user, manage=True)
        if member_id == lib['owner_id']:
            raise HTTPException(422 if lib['role'] == 'owner' else 403, '不能变更或移除学习库创建者。')
        target = con.execute('SELECT role FROM members WHERE library_id=? AND user_id=?', (library_id, member_id)).fetchone()
        if not target:
            raise HTTPException(404, '成员不存在。')
        if lib['role'] != 'owner' and (role == 'admin' or target['role'] not in ('member', 'removed')):
            raise HTTPException(403, '只有创建者可以任免或移除管理员；管理员只能移除或恢复普通成员。')
        if role == 'admin' and target['role'] == 'removed':
            raise HTTPException(409, '请先恢复成员资格，再设置管理员。')
        con.execute('UPDATE members SET role=? WHERE library_id=? AND user_id=?', (role, library_id, member_id))
    return {'ok': True}


@app.get('/api/libraries/{library_id}/posts')
def posts(library_id: str, search: str = '', kind: str = '', favorites: bool = False, offset: int = 0, user=Depends(current_user)):
    if len(search) > 100 or offset < 0:
        raise HTTPException(422, '搜索条件无效。')
    with store.connection() as con:
        membership(con, library_id, user)
        rows = con.execute('''SELECT p.*,u.nickname AS author,
            EXISTS(SELECT 1 FROM favorites f WHERE f.post_id=p.id AND f.user_id=?) AS favorite
            FROM posts p JOIN users u ON u.id=p.author_id WHERE p.library_id=?
            AND (?='' OR p.kind=?) AND (p.title LIKE ? OR p.course LIKE ? OR p.note LIKE ?)
            AND (?=0 OR EXISTS(SELECT 1 FROM favorites f WHERE f.post_id=p.id AND f.user_id=?))
            ORDER BY p.updated_at DESC,p.rowid DESC LIMIT 50 OFFSET ?''',
            (user['id'], library_id,kind,kind, '%'+search+'%','%'+search+'%','%'+search+'%',favorites,user['id'],offset))
        return [dict(r) for r in rows]


@app.post('/api/libraries/{library_id}/posts', status_code=201)
def publish(library_id: str, payload: PostInput, user=Depends(current_user)):
    rate('publish:'+user['id'], 30, 3600)
    post_id = digest(user['id']+':'+library_id+':'+payload.submission_id)
    body = payload.pack.model_dump_json()
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        membership(con, library_id, user)
        existing = con.execute('SELECT p.id,v.pack,v.note FROM posts p JOIN versions v ON v.post_id=p.id AND v.revision=1 WHERE p.id=?', (post_id,)).fetchone()
        if existing:
            if existing['pack'] != body or existing['note'] != payload.note:
                raise HTTPException(409, '这次上传已提交，请刷新后重新选择文件。')
            return {'id': existing['id']}
        if con.execute('SELECT count(*) FROM posts WHERE library_id=?', (library_id,)).fetchone()[0] >= 1000:
            raise HTTPException(409, '学习库内容已达 1000 份，请先整理旧内容。')
        con.execute('INSERT INTO posts(id,library_id,author_id,title,course,kind,note) VALUES (?,?,?,?,?,?,?)',
                    (post_id,library_id,user['id'],payload.pack.title,payload.pack.course,payload.pack.kind,payload.note))
        con.execute('INSERT INTO versions(post_id,revision,pack,note) VALUES (?,1,?,?)', (post_id,body,payload.note))
    return {'id': post_id}


@app.get('/api/posts/{post_id}')
def get_post(post_id: str, revision: int | None = None, user=Depends(current_user)):
    with store.connection() as con:
        post, lib = access_post(con, post_id, user)
        version = con.execute('SELECT * FROM versions WHERE post_id=? AND revision=?', (post_id, revision or post['revision'])).fetchone()
        if not version:
            raise HTTPException(404, '版本不存在。')
        author = con.execute('SELECT nickname FROM users WHERE id=?', (post['author_id'],)).fetchone()['nickname']
        history = [dict(r) for r in con.execute('SELECT revision,note,created_at FROM versions WHERE post_id=? ORDER BY revision DESC', (post_id,))]
        favorite = bool(con.execute('SELECT 1 FROM favorites WHERE post_id=? AND user_id=?', (post_id,user['id'])).fetchone())
        return {**dict(post), 'author':author, 'owner_id':lib['owner_id'], 'view_revision':version['revision'],
                'pack':json.loads(version['pack']), 'note':version['note'], 'history':history, 'favorite':favorite}


@app.get('/api/posts/{post_id}/download')
def download(post_id: str, revision: int | None = None, user=Depends(current_user)):
    post = get_post(post_id, revision, user)
    return JSONResponse(post['pack'], headers={'Content-Disposition':'attachment; filename="zhixi-study-pack.json"'})


@app.put('/api/posts/{post_id}')
def revise(post_id: str, payload: RevisionInput, user=Depends(current_user)):
    rate('publish:'+user['id'], 30, 3600)
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        post, _ = access_post(con, post_id, user, edit=True)
        if payload.revision != post['revision']:
            raise HTTPException(409, '内容已更新，请刷新后核对再上传修订。')
        if post['revision'] >= 20:
            raise HTTPException(409, '单份内容最多保留 20 个版本，请另行发布。')
        rev = post['revision']+1
        con.execute("UPDATE posts SET title=?,course=?,kind=?,note=?,revision=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (payload.pack.title,payload.pack.course,payload.pack.kind,payload.note,rev,post_id))
        con.execute('INSERT INTO versions(post_id,revision,pack,note) VALUES (?,?,?,?)', (post_id,rev,payload.pack.model_dump_json(),payload.note))
    return {'id':post_id, 'revision':rev}


@app.delete('/api/posts/{post_id}')
def remove_post(post_id: str, user=Depends(current_user)):
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        post, lib = access_post(con, post_id, user)
        if user['id'] != post['author_id'] and lib['role'] not in ('owner','admin'):
            raise HTTPException(403, '仅发布者、创建者或管理员可删除内容。')
        con.execute('DELETE FROM posts WHERE id=?', (post_id,))
    return {'ok': True}


@app.put('/api/posts/{post_id}/favorite')
def favorite(post_id: str, enabled: bool, user=Depends(current_user)):
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        access_post(con, post_id, user)
        if enabled:
            con.execute('INSERT OR IGNORE INTO favorites VALUES (?,?)', (user['id'],post_id))
        else:
            con.execute('DELETE FROM favorites WHERE user_id=? AND post_id=?', (user['id'],post_id))
    return {'ok': True}


DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if (DIST / 'assets').exists():
    app.mount('/assets', StaticFiles(directory=DIST/'assets'), name='assets')


@app.get('/{path:path}')
def page(path: str):
    if path.startswith('api/') or not (DIST/'library.html').exists():
        raise HTTPException(404, '页面不存在；请先构建前端。')
    return FileResponse(DIST/'library.html')
