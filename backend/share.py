"""Portable question content: never includes credentials, source files or user progress."""
import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import BlankAnswer, QuestionType

MAX_PACK_BYTES = 2 * 1024 * 1024


class SharedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: QuestionType
    points: float = Field(gt=0, le=100, allow_inf_nan=False)
    stem: str = Field(min_length=5, max_length=12000)
    options: list[str] = Field(default_factory=list, max_length=4)
    answer: str = Field(min_length=1, max_length=12000)
    explanation: str = Field(default='', max_length=20000)
    rubric: list[str] = Field(default_factory=list, max_length=12)
    knowledge: str = Field(default='', max_length=300)
    blanks: list[BlankAnswer] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def valid_structure(self):
        if any(len(v) > 12000 for v in self.options + self.rubric):
            raise ValueError('选项或评分要点过长')
        if self.type == 'choice' and (len(self.options) != 4 or self.answer not in 'ABCD' or len(self.answer) != 1):
            raise ValueError('单选题需要四个选项和 A/B/C/D 标准答案')
        if self.type != 'choice' and self.options:
            raise ValueError('非选择题不应包含选项')
        if self.type == 'true_false' and self.answer not in ('正确', '错误'):
            raise ValueError('判断题标准答案须为正确或错误')
        if self.type != 'fill' and self.blanks:
            raise ValueError('非填空题不应包含逐空答案')
        if self.type == 'fill' and self.blanks:
            indices = [int(n) for n in re.findall(r'\[\[blank:(\d+)\]\]', self.stem)]
            if indices != list(range(1, len(self.blanks) + 1)):
                raise ValueError('逐空答案与题干编号不一致')
        return self


class StudyPack(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['zhixi-study-pack'] = 'zhixi-study-pack'
    version: Literal[1] = 1
    kind: Literal['exam', 'mistakes'] = 'exam'
    title: str = Field(min_length=1, max_length=100)
    course: str = Field(min_length=1, max_length=80)
    questions: list[SharedQuestion] = Field(min_length=1, max_length=30)

    @model_validator(mode='after')
    def bounded(self):
        if not self.title.strip() or not self.course.strip():
            raise ValueError('标题和课程不能为空')
        if len(self.model_dump_json().encode()) > MAX_PACK_BYTES:
            raise ValueError('试卷包不得超过 2 MB')
        return self


def export_pack(title, course, questions, kind='exam'):
    return StudyPack(title=title, course=course, kind=kind, questions=[
        {key: q[key] for key in SharedQuestion.model_fields} for q in questions
    ])


def import_pack(pack):
    from . import db
    exam_id, course_id = uuid.uuid4().hex, uuid.uuid4().hex
    config = {'course_id': course_id, 'title': pack.title, 'ranges': [], 'rules': [],
              'mode': 'custom', 'difficulty': '基础巩固', 'focus': '', 'duration': 60,
              'style': '适度变式', 'imported': True, 'kind': pack.kind}
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        existing = con.execute('SELECT id FROM courses WHERE name=? ORDER BY created_at LIMIT 1', (pack.course,)).fetchone()
        if existing:
            course_id = existing['id']
            config['course_id'] = course_id
        else:
            con.execute('INSERT INTO courses(id,name,description) VALUES (?,?,?)', (course_id, pack.course, '从共享试卷包导入'))
        con.execute("INSERT INTO exams(id,course_id,title,config,status) VALUES (?,?,?,?,'ready')", (exam_id, course_id, pack.title, db.dump(config)))
        for pos, q in enumerate(pack.questions, 1):
            con.execute("""INSERT INTO questions(id,exam_id,position,type,points,status,stem,options,answer,explanation,rubric,knowledge,blanks)
                VALUES (?,?,?,?,?,'ready',?,?,?,?,?,?,?)""", (uuid.uuid4().hex, exam_id, pos, q.type, q.points,
                q.stem, db.dump(q.options), q.answer, q.explanation, db.dump(q.rubric), q.knowledge,
                db.dump([b.model_dump() for b in q.blanks])))
    return exam_id
