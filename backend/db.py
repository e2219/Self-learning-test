import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


@contextmanager
def connection():
    con = sqlite3.connect(DATA_DIR / "study.sqlite3", timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    (DATA_DIR / "uploads").mkdir(exist_ok=True, mode=0o700)
    with connection() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            name TEXT NOT NULL, kind TEXT NOT NULL, page_count INTEGER NOT NULL,
            outline TEXT NOT NULL DEFAULT '[]', warnings TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS pages (
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            number INTEGER NOT NULL, text TEXT NOT NULL, warning TEXT NOT NULL DEFAULT '',
            edited INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(document_id, number)
        );
        CREATE TABLE IF NOT EXISTS exams (
            id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            error TEXT NOT NULL DEFAULT '', tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY, exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, type TEXT NOT NULL, points REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', stem TEXT NOT NULL DEFAULT '',
            options TEXT NOT NULL DEFAULT '[]', answer TEXT NOT NULL DEFAULT '',
            explanation TEXT NOT NULL DEFAULT '', rubric TEXT NOT NULL DEFAULT '[]',
            knowledge TEXT NOT NULL DEFAULT '', sources TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '', user_answer TEXT NOT NULL DEFAULT '',
            self_score REAL, is_wrong INTEGER NOT NULL DEFAULT 0, is_favorite INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            user_answer TEXT NOT NULL, score REAL NOT NULL, snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS ocr_jobs (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            start INTEGER NOT NULL, end INTEGER NOT NULL, force INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued', tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS ocr_job_pages (
            job_id TEXT NOT NULL REFERENCES ocr_jobs(id) ON DELETE CASCADE,
            number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(job_id, number)
        );
        CREATE INDEX IF NOT EXISTS idx_ocr_document ON ocr_jobs(document_id);
        CREATE INDEX IF NOT EXISTS idx_documents_course ON documents(course_id);
        CREATE INDEX IF NOT EXISTS idx_exams_course ON exams(course_id);
        CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam_id);
        """)
        if "ocr_done" not in {r["name"] for r in con.execute("PRAGMA table_info(pages)")}:
            con.execute("ALTER TABLE pages ADD COLUMN ocr_done INTEGER NOT NULL DEFAULT 0")
        con.execute("UPDATE ocr_job_pages SET status='failed',error='服务重启中断识别，请重试。' WHERE status='running'")
        con.execute("UPDATE ocr_jobs SET status='partial' WHERE status IN ('queued','running','cancelling')")
        con.execute("UPDATE questions SET status='failed', error='服务重启中断了生成，请重试。' WHERE status IN ('pending','generating')")
        con.execute("UPDATE exams SET status='partial', error='服务重启中断了生成，已完成题目已保存。' WHERE status IN ('queued','generating')")
    try:
        (DATA_DIR / "study.sqlite3").chmod(0o600)
    except OSError:
        pass


def rows(sql, args=()):
    with connection() as con:
        return [dict(row) for row in con.execute(sql, args).fetchall()]


def one(sql, args=()):
    result = rows(sql, args)
    return result[0] if result else None


def execute(sql, args=()):
    with connection() as con:
        con.execute(sql, args)


def setting(key, default=""):
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def decode(row, fields):
    if row is None:
        return None
    for field in fields:
        row[field] = json.loads(row[field])
    return row


def question(row):
    return decode(row, ("options", "rubric", "sources"))


def dump(value):
    return json.dumps(value, ensure_ascii=False)
