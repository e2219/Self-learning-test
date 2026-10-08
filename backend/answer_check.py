"""Literal answer matching only; no model calls or symbolic equivalence guesses."""
import json
from decimal import Decimal, ROUND_HALF_UP

from .models import AnswerCheckInput


def normalize(value):
    # Preserve case, signs, inner spacing, symbols and mathematical notation.
    value=value.replace('\r\n','\n').replace('\r','\n').strip()
    # A single math wrapper is presentation, not an algebraic transformation.
    for left,right in (('$$','$$'),('$','$'),('\\(','\\)'),('\\[','\\]')):
        if value.startswith(left) and value.endswith(right) and len(value)>len(left)+len(right):
            value=value[len(left):-len(right)].strip(); break
    return value


def check(question, payload):
    if question['type'] in ('choice','true_false'):
        answers=[payload.answer]
        accepted=[[question['answer']]]
    elif question['type']=='fill' and question['blanks']:
        if len(payload.blanks)!=len(question['blanks']):
            raise ValueError('请按空位逐项填写；未作答的空位保留为空。')
        answers=payload.blanks
        accepted=[[b['answer'],*b['alternatives']] for b in question['blanks']]
    else: raise ValueError('此题不支持本地核验；旧版填空题需先补全逐空标准答案，计算和证明题请自行评分。')
    statuses=['empty' if not normalize(a) else 'match' if normalize(a) in {normalize(v) for v in refs} else 'different' for a,refs in zip(answers,accepted)]
    earned=Decimal(str(question['points']))*statuses.count('match')/len(statuses)
    score=float(earned.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    return {'items':[{'number':i+1,'status':s} for i,s in enumerate(statuses)],'suggested_score':score,
        'all_answered':'empty' not in statuses,'all_match':all(s=='match' for s in statuses),
        'message':'仅核对与标准答案及已列等价答案是否一致，不验证标准答案本身。未作答单独标记，可人工修改评分。'}


def check_saved_answer(question, answer):
    blanks = []
    if question['type'] == 'fill' and question['blanks']:
        if not answer.strip():
            blanks = [''] * len(question['blanks'])
        else:
            try:
                blanks = json.loads(answer)
            except (ValueError, TypeError) as exc:
                raise ValueError('请按空位填写答案后保存；旧版整段作答仍保留。') from exc
            if not isinstance(blanks, list) or not all(isinstance(item, str) for item in blanks):
                raise ValueError('请按空位填写答案后保存。')
    return check(question, AnswerCheckInput(answer=answer, blanks=blanks))
