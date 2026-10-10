"""Reuse only reviews which passed semantic checks for the exact same request."""
from . import db, drafts, providers
VERSION = 'review-checkpoint-v1'


def signature(messages, context):
    return drafts.digest({'version':VERSION,'messages':messages,'context':context,
        'providers':[providers.identity('text'),providers.identity('vision')]})


def get(question_id, stage, messages, context):
    if not question_id: return None
    row=db.one('SELECT * FROM review_checkpoints WHERE question_id=? AND stage=?',(question_id,stage))
    if row and row['signature']==signature(messages,context):
        import json
        return json.loads(row['response'])


def save(question_id, stage, messages, context, response):
    if not question_id or not db.one('SELECT 1 FROM questions WHERE id=?',(question_id,)): return
    db.execute('INSERT OR REPLACE INTO review_checkpoints VALUES (?,?,?,?)',
        (question_id,stage,signature(messages,context),db.dump(response)))
