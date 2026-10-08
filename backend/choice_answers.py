"""Canonical option sets, shared by generation, review and local grading."""
import re

CHOICE_TYPES = ('choice', 'multiple_choice', 'indefinite_choice')
MULTI_TYPES = ('multiple_choice', 'indefinite_choice')


def canonical(value: str, minimum=0):
    compact = re.sub(r'[\s,，、;；]+', '', value).upper()
    if any(c not in 'ABCD' for c in compact) or len(set(compact)) != len(compact):
        raise ValueError('选择题答案仅可包含不重复的 A、B、C、D。')
    if len(compact) < minimum:
        raise ValueError(f'此题至少需要 {minimum} 个正确选项。')
    return ''.join(sorted(compact))
