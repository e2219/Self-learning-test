import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from . import db

failures = defaultdict(list)


def hash_code(code, salt):
    return hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), 200_000).hex()


def initialize_access():
    env_code = os.environ.get("STUDY_ACCESS_CODE")
    if env_code and len(env_code) < 8:
        raise RuntimeError("STUDY_ACCESS_CODE 至少需要 8 个字符")
    if env_code or db.setting("access_hash"):
        return
    code = secrets.token_urlsafe(12)
    salt = secrets.token_hex(16)
    db.set_setting("access_salt", salt)
    db.set_setting("access_hash", hash_code(code, salt))
    path = db.DATA_DIR / "access-code.txt"
    # Contains only the initial local access code, never the API key.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(code + "\n")


def login(code, address):
    now = time.time()
    # Bound in-memory rate-limit state on a long-running LAN service.
    for ip in list(failures):
        failures[ip] = [t for t in failures[ip] if t > now - 300]
        if not failures[ip]:
            del failures[ip]
    if len(failures[address]) >= 10:
        raise HTTPException(429, "尝试次数过多，请 5 分钟后重试。")
    env_code = os.environ.get("STUDY_ACCESS_CODE")
    valid = hmac.compare_digest(code.encode(), env_code.encode()) if env_code else hmac.compare_digest(
        hash_code(code, db.setting("access_salt")), db.setting("access_hash")
    )
    if not valid:
        failures[address].append(now)
        raise HTTPException(401, "访问口令不正确，请查看电脑上的启动终端。")
    failures.pop(address, None)
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires<?", (now,))
    db.execute("INSERT INTO sessions VALUES (?,?)", (hashlib.sha256(token.encode()).hexdigest(), now + 86400 * 7))
    return token


def require_auth(request: Request):
    token = request.cookies.get("study_session", "")
    row = db.one("SELECT expires FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    if not row or row["expires"] < time.time():
        raise HTTPException(401, "请先输入访问口令。")


def api_key():
    return os.environ.get("DEEPSEEK_API_KEY", "") or db.setting("api_key")
