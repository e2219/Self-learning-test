"""Consistent SQLite snapshot + immutable document files; no credentials in export."""
from datetime import datetime, timezone
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile

from . import db

TABLES = {'courses', 'documents', 'pages', 'exams', 'questions', 'attempts', 'ocr_jobs',
          'ocr_job_pages', 'exam_plans', 'plan_revisions', 'topic_cache', 'exam_submissions',
          'ocr_cache', 'usage_events'}
_building = threading.Lock()
_pending_lock = threading.Lock()
_pending = {}
TTL = 15 * 60


class BackupError(ValueError):
    pass


def cleanup_expired():
    for key, item in list(_pending.items()):
        if time.monotonic() - item['created'] > TTL:
            _pending.pop(key)['temporary'].cleanup()


def take(key):
    with _pending_lock:
        cleanup_expired()
        return _pending.pop(key, None)


def create():
    if not _building.acquire(blocking=False):
        raise BackupError('正在制作备份，请稍后再试。')
    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix='zhixi-backup-')
        with _pending_lock:
            cleanup_expired()
            if len(_pending) >= 3:
                raise BackupError('已有待下载的备份，请先下载或等待链接过期后再试。')
        root = Path(temporary.name)
        snapshot = root / 'study.sqlite3'
        # SQLite backup captures a consistent view, including committed WAL contents.
        with db.connection() as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        with closing(sqlite3.connect(snapshot)) as con:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA journal_mode=DELETE')
            con.execute('PRAGMA secure_delete=ON')
            # Allow-list avoids exporting retired plugins' session/token tables, too.
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                name = row['name']
                if name not in TABLES and not name.startswith('sqlite_'):
                    con.execute('DROP TABLE "' + name.replace('"', '""') + '"')
            con.commit()
            con.execute('VACUUM')  # Remove deleted settings, sessions and unused pages from the file.
            docs = con.execute('SELECT id FROM documents ORDER BY id').fetchall()
            counts = {table:con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                      for table in ('courses','documents','exams','questions','attempts')}
        snapshot.chmod(0o600)
        filename = '知习备份-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip'
        archive = root / 'backup.zip'
        with zipfile.ZipFile(archive, 'w', allowZip64=True) as zipped:
            zipped.write(snapshot, 'data/study.sqlite3', compress_type=zipfile.ZIP_DEFLATED)
            for doc in docs:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', doc['id']):
                    raise BackupError('资料文件标识异常，未生成备份。')
                path = db.DATA_DIR / 'uploads' / (doc['id'] + '.pdf')
                if path.is_symlink() or not path.is_file():
                    raise BackupError('部分资料文件缺失或正在删除，未生成完整备份；请检查资料后重试。')
                zipped.write(path, 'data/uploads/' + path.name, compress_type=zipfile.ZIP_STORED)
            zipped.writestr('manifest.json', json.dumps({'format':'zhixi-backup', 'version':1,
                'created_at':datetime.now(timezone.utc).isoformat(), 'counts':counts,
                'excluded':['API keys','settings','sessions','access codes']}, ensure_ascii=False, indent=2))
            zipped.writestr('恢复说明.txt',
                '此备份包含课程、教材、试卷、作答历史与缓存，不含应用设置、API Key、登录会话和访问口令。\n'
                '恢复步骤：\n1. 关闭项目服务，使用相同或更新版本的项目。\n'
                '2. 将现有 data 目录改名另存（设置过 STUDY_DATA_DIR 时使用该目录）。\n'
                '3. 将备份中的 data 整个目录放到原位置，不要与旧目录合并，也不要复制旧的 sqlite3-wal/shm 文件。\n'
                '4. 运行 python start.py，使用终端显示的新口令登录，重新配置模型接口和 API Key。\n'
                '如设置了环境变量口令或密钥，仍以环境变量为准。后台未完成的任务在恢复后需手动继续。\n')
        snapshot.unlink()
        key = uuid.uuid4().hex
        with _pending_lock:
            _pending[key] = dict(temporary=temporary, path=archive, filename=filename, created=time.monotonic())
        return {'url':'/api/backups/' + key, 'filename':filename, 'counts':counts}
    except BackupError:
        if temporary: temporary.cleanup()
        raise
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        if temporary: temporary.cleanup()
        raise BackupError('备份失败，请检查磁盘空间，避免同时删除资料，然后重试。') from exc
    except BaseException:
        if temporary: temporary.cleanup()
        raise
    finally:
        _building.release()
