"""Conservative, bounded checks for explicit closed arithmetic and propositional identities.
No eval, symbolic algebra service, code execution or model calls. Unsupported syntax is skipped.
These checks validate individual assertions, never an entire answer or proof.
"""
import ast
from fractions import Fraction
from itertools import product
import math
import re


class LocalQualityError(ValueError):
    pass


def numeric(text):
    """Return an exact rational for a small, variable-free expression, or None."""
    if not isinstance(text, str) or len(text) > 400:
        return None
    text = text.strip().strip('$').strip()
    text = text.replace(r'\left', '').replace(r'\right', '').replace(r'\,', '').replace(r'\!', '')
    for _ in range(8):
        old = text
        text = re.sub(r'\\(?:dfrac|tfrac|frac)\{([^{}]+)\}\{([^{}]+)\}', r'((\1)/(\2))', text)
        text = re.sub(r'\\binom\{([^{}]+)\}\{([^{}]+)\}', r'comb(\1,\2)', text)
        if old == text: break
    text = text.replace(r'\times', '*').replace(r'\cdot', '*').replace(r'\div', '/')
    text = text.replace('×', '*').replace('÷', '/').replace('−', '-').replace('^', '**')
    text = text.replace('{', '(').replace('}', ')').replace(r'\%', '%')
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'(\1/100)', text)
    text = re.sub(r'(?<![\w.])(\d{1,3})!', r'factorial(\1)', text)
    if len(text) > 800 or re.search(r'\d{41}', text): return None
    try:
        tree = ast.parse(text, mode='eval')
        if len(list(ast.walk(tree))) > 80: return None
        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                token = ast.get_source_segment(text, node)
                if not re.fullmatch(r'\d+(?:\.\d+)?', token): raise ValueError()
                result = Fraction(token)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                result = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): result = a + b
                elif isinstance(node.op, ast.Sub): result = a - b
                elif isinstance(node.op, ast.Mult): result = a * b
                elif isinstance(node.op, ast.Div): result = a / b
                elif isinstance(node.op, ast.Pow) and b.denominator == 1 and abs(b) <= 12: result = a ** int(b)
                else: raise ValueError()
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
                args = [visit(arg) for arg in node.args]
                if any(a.denominator != 1 or not 0 <= a <= 100 for a in args): raise ValueError()
                if node.func.id == 'comb' and len(args) == 2 and args[1] <= args[0]: result = Fraction(math.comb(*map(int, args)))
                elif node.func.id == 'factorial' and len(args) == 1: result = Fraction(math.factorial(int(args[0])))
                else: raise ValueError()
            else: raise ValueError()
            if result.numerator.bit_length() > 4096 or result.denominator.bit_length() > 4096: raise ValueError()
            return result
        return visit(tree.body)
    except (ValueError, TypeError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def truth_values(text, variables):
    """Truth table for a deliberately small propositional notation, or None."""
    if len(text) > 400: return None
    operators = {r'\leftrightarrow':'↔', r'\rightarrow':'→', r'\implies':'→', r'\lnot':'¬',
                 r'\neg':'¬', r'\wedge':'∧', r'\land':'∧', r'\vee':'∨', r'\lor':'∨', r'\iff':'↔', r'\to':'→'}
    for key, val in operators.items(): text = text.replace(key, val)
    text = text.replace(r'\left', '').replace(r'\right', '').replace(' ', '')
    tokens = re.findall(r'[pqrstPQRST]|[¬∧∨→↔()]', text)
    if ''.join(tokens) != text or len(tokens) > 100: return None
    def evaluate(values):
        pos = 0
        def parse(minimum=0):
            nonlocal pos
            if pos >= len(tokens): raise ValueError()
            token = tokens[pos]; pos += 1
            if token == '¬': left = not parse(5)
            elif token == '(':
                left = parse()
                if pos >= len(tokens) or tokens[pos] != ')': raise ValueError()
                pos += 1
            elif token in values: left = values[token]
            else: raise ValueError()
            precedence = {'↔':1,'→':2,'∨':3,'∧':4}
            while pos < len(tokens) and tokens[pos] in precedence and precedence[tokens[pos]] >= minimum:
                op = tokens[pos]; pos += 1
                right = parse(precedence[op] + (0 if op == '→' else 1))
                if op == '∧': left = left and right
                elif op == '∨': left = left or right
                elif op == '→': left = not left or right
                else: left = left == right
            return left
        answer = parse()
        if pos != len(tokens): raise ValueError()
        return answer
    try: return tuple(evaluate(dict(zip(variables, values))) for values in product((False, True), repeat=len(variables)))
    except (ValueError, RecursionError): return None


MATH = re.compile(r'\$\$([\s\S]*?)\$\$|(?<!\$)\$([^$\n]+)\$(?!\$)|\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]')
# Counterexamples, deliberately false statements and rounded values are not asserted identities.
QUALIFIED = re.compile(r'约|近似|舍入|保留|不|非|选项|[ABCD][项：:]|错|误|反例|反证|假设|矛盾|假命题|不正确|不对|若|如果|并非|不能|假如|不应|错写|approx|round|false|incorrect|suppose', re.I)


def check(q, kind):
    counts = {'arithmetic': 0, 'logic': 0, 'numeric_options': 0, 'skipped': 0}
    # Proofs may intentionally derive false identities under a temporary assumption.
    # Without a proof context, a local equation checker must not reject those steps.
    if kind == 'proof': return {**counts, 'scope': 'proof_not_checked'}
    # Equal-valued options are only duplicates when the question asks for a numerical value.
    # Representation/syntax tasks (e.g. simplest fraction) intentionally distinguish equivalent values.
    if kind == 'choice' and re.search(r'值|概率|结果|等于|多少|计算', q.stem) and not re.search(r'形式|写法|表示|分数|小数|百分|化简|最简|约|近似|舍入|保留', q.stem):
        values = [numeric(option) for option in q.options]
        for i, value in enumerate(values):
            if value is not None:
                counts['numeric_options'] += 1
                if value in values[:i]:
                    raise LocalQualityError(f'选项 {"ABCD"[values.index(value)]} 与 {"ABCD"[i]} 的数值完全相同；请修正选项后重新核验答案。')
    for field in (q.answer, q.explanation):
        spans = [(m.start(), m.end(), next(g for g in m.groups() if g is not None)) for m in MATH.finditer(field)]
        if not spans and '=' in field and len(field) < 200: spans = [(0, len(field), field)]
        for start, end, formula in spans:
            # Interpret qualifiers over the surrounding sentence, not an arbitrary short window.
            left = max(field.rfind('。', 0, start), field.rfind('\n\n', 0, start)) + 1
            stops = [i for mark in ('。', '\n\n') if (i := field.find(mark, end)) >= 0]
            context = field[left:min(stops) if stops else len(field)]
            formula = formula.strip().rstrip('.,;。；，')
            if QUALIFIED.search(context + field[max(0, start-35):end+80]) or re.search(r'≈|≠|\\(?:approx|ne|sim|le|ge|not)(?![A-Za-z])', formula):
                counts['skipped'] += 1; continue
            if r'\equiv' in formula or '≡' in formula:
                sides = re.split(r'\\equiv|≡', formula)
                variables = sorted(set(re.findall(r'(?<![A-Za-z])[pqrstPQRST](?![A-Za-z])', formula)))
                if len(sides) == 2 and 0 < len(variables) <= 5:
                    tables = [truth_values(s.strip(), variables) for s in sides]
                    if all(t is not None for t in tables):
                        counts['logic'] += 1
                        if tables[0] != tables[1]: raise LocalQualityError('解析中的命题逻辑等价式未通过真值表核验：' + formula[:160])
                        continue
                counts['skipped'] += 1
            elif '=' in formula and not re.search(r'[<>!]=|=>', formula):
                # A symbolic prefix such as P(A)= can coexist with a checkable numeric tail.
                # Only compare adjacent closed expressions, never substitute into variables.
                values = [numeric(s) for s in formula.split('=')]
                for a, b in zip(values, values[1:]):
                    if a is None or b is None:
                        counts['skipped'] += 1
                        continue
                    counts['arithmetic'] += 1
                    if a != b: raise LocalQualityError('解析或答案中的数值等式不成立：' + formula[:160])
    return {**counts, 'scope': 'closed_expressions_only'}


def task_contract(kind, difficulty):
    form = {
        'choice':'恰有一个正确选项；干扰项应对应具体误区，不能用“更契合”排除正确项。',
        'multiple_choice':'至少两个正确选项；逐项真值与答案集合完全一致。',
        'indefinite_choice':'一个或多个正确选项；不透露正确数量，逐项核对答案集合。',
        'true_false':'一项明确、可判定的陈述；不能把两个独立结论混成一句。',
        'fill':'每空只填短术语、数值或表达式；不要求解释或证明。',
        'calculation':'给足变量、数据、单位及必要假设；所问结果必须需要计算。',
        'proof':'明确假设与待证结论；给出推理链，不能以举例代替一般证明。',
    }
    depth = {'基础巩固':'直接运用目标概念或公式，不靠冗长文字和偏门条件增加难度。',
             '综合应用':'围绕已分配目标连接必要推理步骤，列全依赖条件。',
             '挑战题':'在资料范围内增加推理深度或迁移，不能凭空引入未分配考点。'}
    return {'form':form[kind], 'depth':depth.get(difficulty,depth['基础巩固'])}
