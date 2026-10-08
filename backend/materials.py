"""Table eligibility checks. Structural checks cannot certify OCR accuracy."""
import hashlib
import re


def table_info(text, flagged=False, reviewed=False):
    rows = [line.strip() for line in text.splitlines() if re.search(r'(?<!\\)\|', line)]
    has_table = bool(flagged or len(rows) >= 2 or re.search(r'<table|\[表格|\t.+\t', text, re.I))
    issues = []
    tables, current = [], []
    for line in text.splitlines() + ['']:
        if re.search(r'(?<!\\)\|', line):
            cells = re.split(r'(?<!\\)\|', line.strip().strip('|'))
            current.append([c.strip() for c in cells])
        elif current:
            tables.append(current); current = []
    for table in tables:
        if len(table) < 2:
            continue
        widths = {len(row) for row in table}
        if len(widths) != 1:
            issues.append('表格各行列数不一致，请核对合并单元格与缺失数据。')
        if not any(all(re.fullmatch(r':?-{3,}:?', cell) for cell in row) for row in table):
            issues.append('表格缺少明确的表头分隔行，请补全 Markdown 表头。')
    if has_table and ('[无法辨认]' in text or '[表格待核对]' in text):
        issues.append('存在无法辨认的数据或待核对标记。')
    if has_table and not tables:
        issues.append('疑似表格尚未整理为带表头的 Markdown 表格。')
    if has_table and len(text) > 14000:
        issues.append('此表格页过长，请拆分资料或缩小表格内容后再使用。')
    return {'has_table': has_table, 'table_issues': list(dict.fromkeys(issues)),
            'needs_review': has_table and (not reviewed or bool(issues)),
            'text_hash': hashlib.sha256(text.encode()).hexdigest()}


def page_info(page):
    info = table_info(page['text'], page.get('table_flag', False), page.get('table_reviewed', False))
    # Vision output with valid structure is usable without a human confirmation.
    # Explicitly flagged pages remain blocked; never label automatic checks as human review.
    info['auto_usable'] = bool(page.get('ocr_done') and not page.get('edited')
                               and not page.get('table_flag') and not info['table_issues'])
    if info['auto_usable']:
        info['needs_review'] = False
    return info


def chunks(page):
    info = page_info(page)
    if info['needs_review']:
        return []
    # Keep the whole eligible page including title, units and footnotes. No table slicing.
    if info['has_table']:
        return [page['text'].strip()]
    return [page['text'][offset:offset + 2800].strip() for offset in range(0, len(page['text']), 2400)]
