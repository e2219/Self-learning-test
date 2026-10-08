import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get('LIBRARY_DATA_DIR', Path(__file__).resolve().parents[2] / 'library-data'))


@contextmanager
def connection():
    con = sqlite3.connect(DATA_DIR / 'library.sqlite3', timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize():
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    DATA_DIR.chmod(0o700)
    with connection() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, nickname TEXT NOT NULL,
                salt TEXT NOT NULL, password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS libraries (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                owner_id TEXT NOT NULL REFERENCES users(id), invite_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS members (
                library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL,
                PRIMARY KEY(library_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY, library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
                author_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, course TEXT NOT NULL,
                kind TEXT NOT NULL, note TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS versions (
                post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL, pack TEXT NOT NULL, note TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                PRIMARY KEY(post_id,revision)
            );
            CREATE TABLE IF NOT EXISTS favorites (
                user_id TEXT NOT NULL REFERENCES users(id), post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                PRIMARY KEY(user_id,post_id)
            );
            CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_posts_library ON posts(library_id,updated_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        ''')
        columns = {r['name'] for r in con.execute('PRAGMA table_info(libraries)')}
        for name in ('access_salt', 'access_hash'):
            if name not in columns:
                con.execute(f"ALTER TABLE libraries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    (DATA_DIR / 'library.sqlite3').chmod(0o600)
