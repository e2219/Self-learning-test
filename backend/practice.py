"""Re-use wrong questions locally, with independent answers and scores."""
from collections import Counter
from datetime import datetime
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field
from . import db


class PracticeInput(BaseModel):
    course_id: str = Field(min_length=1, max_length=100)
    submission_id: str = Field(min_length=8, max_length=100)


CONTENT = ('type', 'points', 'stem', 'options', 'answer', 'blanks')
COPY = ('type', 'points', 'stem', 'options', 'answer', 'explanation', 'rubric', 'knowledge', 'sources', 'blanks', 'review')


def create(payload):
    key = 'practice:' + payload.submission_id
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT * FROM exam_submissions WHERE key=?', (key,)).fetchone()
        if old:
            if old['request_hash'] != payload.course_id:
                raise HTTPException(409, '同一练习提交不能更换课程。')
            if not con.execute('SELECT 1 FROM exams WHERE id=?', (old['exam_id'],)).fetchone():
                raise HTTPException(410, '这份练习已删除，请重新开始。')
            return old['exam_id']
        course = con.execute('SELECT * FROM courses WHERE id=?', (payload.course_id,)).fetchone()
        if not course: raise HTTPException(404, '课程不存在。')
        questions = con.execute('''SELECT q.* FROM questions q JOIN exams e ON e.id=q.exam_id
            WHERE e.course_id=? AND q.status='ready' AND q.is_wrong=1 AND q.practice_source_id IS NULL
            ORDER BY RANDOM() LIMIT 10''', (payload.course_id,)).fetchall()
        if not questions: raise HTTPException(422, '这门课程没有可练习的错题。')
        exam_id = uuid.uuid4().hex
        title = (course['name'][:65] + ' · 错题练习 ' + datetime.now().strftime('%m-%d %H:%M'))
        counts = Counter((q['type'], q['points']) for q in questions)
        config = dict(course_id=payload.course_id, title=title, practice=True, ranges=[],
                      rules=[dict(type=t, points=p, count=n) for (t,p),n in counts.items()],
                      mode='custom', difficulty='错题巩固', duration=30, token_budget=0, max_attempts=1)
        con.execute("INSERT INTO exams(id,course_id,title,config,status) VALUES (?,?,?,?,'ready')",
                    (exam_id, payload.course_id, title, db.dump(config)))
        for position, question in enumerate(questions, 1):
            fields = ('id', 'exam_id', 'position', 'status', 'practice_source_id', *COPY)
            con.execute(f'INSERT INTO questions({",".join(fields)}) VALUES ({",".join("?" for _ in fields)})',
                        (uuid.uuid4().hex, exam_id, position, 'ready', question['id'], *(question[k] for k in COPY)))
        con.execute('INSERT INTO exam_submissions(key,request_hash,exam_id) VALUES (?,?,?)',
                    (key, payload.course_id, exam_id))
        return exam_id


def record_source_result(con, question, values):
    """Update review membership, never overwrite the original answer/score.

    Only matching versions can affect the original's review status. Modified/deleted
    originals and edited practice copies keep independent records.
    """
    source_id = question.get('practice_source_id')
    if not source_id or values.get('self_score') is None: return
    source = con.execute('SELECT * FROM questions WHERE id=?', (source_id,)).fetchone()
    if not source or source['status'] != 'ready' or any(source[k] != question[k] for k in CONTENT): return
    snapshot = db.question(dict(source))
    snapshot['practice_exam_id'] = question['exam_id']
    con.execute('INSERT INTO attempts(id,question_id,user_answer,score,snapshot) VALUES (?,?,?,?,?)',
                (uuid.uuid4().hex, source_id, values.get('user_answer', question['user_answer']),
                 values['self_score'], db.dump(snapshot)))
    con.execute('UPDATE questions SET is_wrong=? WHERE id=?', (values['self_score'] < source['points'], source_id))
