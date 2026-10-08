"""Persisted draft revisions and source-change detection. No model calls."""
import hashlib
import json

from fastapi import HTTPException
from . import db


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def clean_config(config):
    return {k:v for k,v in config.items() if k not in ('blueprint','plan_id','submission_id','parent_plan_id')}


def source_manifest(config):
    result = {}
    course = db.one('SELECT name,description FROM courses WHERE id=?', (config['course_id'],))
    result['course'] = digest(course)
    for r in config['ranges']:
        doc = db.one('SELECT kind FROM documents WHERE id=?', (r['document_id'],))
        pages = {p.pop('number'):p for p in db.rows('SELECT number,text,edited,ocr_done,table_flag,table_reviewed FROM pages WHERE document_id=? AND number BETWEEN ? AND ?', (r['document_id'],r['start'],r['end']))}
        for n in range(r['start'], r['end']+1):
            page = pages.get(n)
            result[f"{r['document_id']}:{n}"] = digest({'page':page,'kind':doc})
    return result


def changes(row):
    config = json.loads(row['config'])
    old = json.loads(row['manifest'])
    now = source_manifest(config)
    if not old:
        return [{'label':'旧版规划缺少完整资料版本，请重新核验', 'key':'legacy'}]
    result=[]
    for key in old.keys() | now.keys():
        if old.get(key)==now.get(key): continue
        if key=='course': label='课程名称或说明已变化'
        else:
            doc_id, number=key.rsplit(':',1)
            doc=db.one('SELECT name FROM documents WHERE id=?',(doc_id,))
            label=f"{doc['name'] if doc else '已删除资料'} · PDF 第 {number} 页内容或核对状态已变化"
        result.append({'key':key,'label':label})
    return result


def settings_changed(original, current):
    original={**original,'rules':sorted((r for r in original['rules'] if r['count']>0),key=lambda r:r['type'])}
    current={**current,'rules':sorted((r for r in current['rules'] if r['count']>0),key=lambda r:r['type'])}
    ignore={'title','duration','token_budget','max_attempts','batch_generation'}
    return {k:v for k,v in clean_config(original).items() if k not in ignore} != {k:v for k,v in clean_config(current).items() if k not in ignore}


def enrich(row):
    config=json.loads(row['draft_config'] or row['config'])
    blueprint=json.loads(row['draft_blueprint'] or row['blueprint'])
    linked=db.one('SELECT exam_id FROM exam_submissions WHERE key=?',('plan:'+row['id'],))
    changed=changes(row)
    return {'basis_config':json.loads(row['config']), 'config':config,'blueprint':blueprint,'revision':row['revision'],'updated_at':row['updated_at'],
        'source_changes':changed,'needs_replan':bool(changed) or settings_changed(json.loads(row['config']),config),
        'parent_id':row['parent_id'],'exam_id':linked['exam_id'] if linked else None,'cache_hits':row['cache_hits']}


def save(plan_id, payload):
    config=clean_config(payload.config.model_dump())
    blueprint=[s.model_dump() for s in payload.blueprint]
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM exam_plans WHERE id=?',(plan_id,)).fetchone()
        if not row: raise HTTPException(404,'规划不存在。')
        if config['course_id']!=row['course_id']: raise HTTPException(422,'不能把草稿移动到其他课程。')
        if con.execute('SELECT 1 FROM exam_submissions WHERE key=?',('plan:'+plan_id,)).fetchone():
            raise HTTPException(409,'这份规划已提交，请查看对应试卷；需要另一份卷请新建规划。')
        if payload.revision!=row['revision']:
            raise HTTPException(409,'草稿已被其他页面更新。当前输入保留在本机，请重新读取后核对，避免覆盖。')
        if clean_config(json.loads(row['draft_config'] or row['config']))==config and json.loads(row['draft_blueprint'] or row['blueprint'])==blueprint:
            return
        # Preserve the original and every saved revision, never rewrite historical snapshots.
        con.execute('INSERT OR IGNORE INTO plan_revisions(plan_id,revision,config,blueprint) VALUES (?,?,?,?)',
            (plan_id,row['revision'],row['draft_config'] or row['config'],row['draft_blueprint'] or row['blueprint']))
        revision=row['revision']+1
        con.execute("UPDATE exam_plans SET draft_config=?,draft_blueprint=?,revision=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(db.dump(config),db.dump(blueprint),revision,plan_id))
        con.execute('INSERT INTO plan_revisions(plan_id,revision,config,blueprint) VALUES (?,?,?,?)',(plan_id,revision,db.dump(config),db.dump(blueprint)))


def history(plan_id):
    result=[]; seen=set()
    while plan_id and plan_id not in seen and len(seen)<20:
        seen.add(plan_id)
        row=db.one('SELECT * FROM exam_plans WHERE id=?',(plan_id,))
        if not row: break
        revisions=db.rows('SELECT revision,config,blueprint,created_at FROM plan_revisions WHERE plan_id=? ORDER BY revision DESC',(plan_id,))
        if not revisions: revisions=[{'revision':0,'config':row['config'],'blueprint':row['blueprint'],'created_at':row['updated_at']}]
        result.extend({'plan_id':plan_id,**db.decode(r,('config','blueprint'))} for r in revisions)
        plan_id=row['parent_id']
    return result
