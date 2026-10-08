import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Query, APIRouter, BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import providers, web_resources
from . import db, limits, security, ocr, deepseek, materials, planning, drafts, answer_check, usage, explanations
from .generation import GenerationError, active_exams, plan_questions, retrieve, material_candidates, run_generation, validate_content
from .choice_answers import MULTI_TYPES, canonical
from .models import CourseInput, ExamInput, LoginInput, PageInput, OCRInput, ProgressInput, QuestionEdit, SettingsInput, TableReviewInput, RegionInput, PlanSaveInput, AnswerCheckInput, BudgetInput, OCRBudgetInput
from .pdf import PDFError, PDFSizeError, save_and_extract_pdf, text_quality_issue, save_image_as_pdf


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    security.initialize_access()
    yield


app = FastAPI(title="知习 · AI 学习助手", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    if request.url.path.startswith('/api/settings'):
        # Pydantic's default errors include input (potentially the entire API key).
        return JSONResponse({'detail': '接口设置格式无效，请检查地址、模型 ID 和密钥格式。'}, status_code=422)
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def same_origin(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "不允许跨站请求。"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "不允许跨站请求。"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/login")
def login(payload: LoginInput, request: Request, response: Response):
    token = security.login(payload.code, request.client.host if request.client else "unknown")
    response.set_cookie("study_session", token, httponly=True, samesite="strict", max_age=86400 * 7,
        secure=request.url.scheme == "https")
    return {"ok": True}


api = APIRouter(prefix="/api", dependencies=[Depends(security.require_auth)])


def required(table, item_id):
    # Table names are internal constants, never supplied by HTTP callers.
    row = db.one(f"SELECT * FROM {table} WHERE id=?", (item_id,))
    if not row:
        raise HTTPException(404, "内容不存在。")
    return row


def ensure_idle(exam_id):
    exam = required("exams", exam_id)
    if exam["status"] in ("queued", "generating") or exam_id in active_exams:
        raise HTTPException(409, "试卷正在生成，请等待完成，或暂停后再操作。")
    return exam


def exam_detail(exam_id):
    exam = db.decode(required("exams", exam_id), ("config",))
    exam["course_name"] = required("courses", exam["course_id"])["name"]
    exam["questions"] = [db.question(q) for q in db.rows("SELECT * FROM questions WHERE exam_id=? ORDER BY position", (exam_id,))]
    exam["usage"] = usage.summary("exam", exam_id)
    exam["total_points"] = sum(q["points"] for q in exam["questions"])
    if exam["config"].get("plan_id"):
        plan = planning.detail(exam["config"]["plan_id"])
        if plan:
            slots = exam["config"].get("blueprint", [])
            ready = {q["position"] for q in exam["questions"] if q["status"] == "ready"}
            exam["coverage"] = [{"title": t["title"], "planned": sum(s["topic_id"] == t["id"] for s in slots),
                "completed": sum(s["topic_id"] == t["id"] and i in ready for i,s in enumerate(slots, 1))} for t in plan["topics"]]
            exam["planning_tokens"] = plan["tokens"]
    return exam


@api.get("/session")
def session():
    return {"authenticated": True}


@api.post("/logout")
def logout(request: Request, response: Response):
    digest = hashlib.sha256(request.cookies.get("study_session", "").encode()).hexdigest()
    db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
    response.delete_cookie("study_session")
    return {"ok": True}


@api.get("/settings")
def settings():
    return {"deepseek_has_key": bool(security.api_key()), "has_key": providers.has_key(), "has_vision_key": providers.has_key("vision"),
        "providers": {role: providers.public(role) for role in ("text", "vision")}, "key_from_env": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "model": db.setting("model", "deepseek-chat"),
        "ocr_model": providers.config("vision")["model"], "ocr_max_pages": ocr.MAX_PAGES,
        "max_pdf_bytes": limits.MAX_PDF_BYTES, "max_pdf_pages": limits.MAX_PDF_PAGES}


@api.post("/settings/test-connection")
async def test_connection():
    try:
        return await deepseek.check_connection(ocr.MODEL)
    except deepseek.ClientSetupError as exc:
        raise HTTPException(422, str(exc)) from exc


@api.put("/settings")
def update_settings(payload: SettingsInput):
    ensure_provider_idle()
    if payload.clear_key:
        db.set_setting("api_key", "")
    elif payload.api_key.strip():
        db.set_setting("api_key", payload.api_key.strip())
    db.set_setting("model", payload.model)
    return settings()


def ensure_provider_idle():
    if active_exams or planning.active_plans or ocr.active_jobs or any((
        db.one("SELECT 1 FROM exams WHERE status IN ('queued','generating')"),
        db.one("SELECT 1 FROM exam_plans WHERE status IN ('queued','running')"),
        db.one("SELECT 1 FROM ocr_jobs WHERE status IN ('queued','running')"),
    )):
        raise HTTPException(409, '有 AI 任务正在执行，请等待完成或停止任务后再修改接口。')


@api.put('/settings/providers/{role}')
def save_provider(role: providers.Role, payload: providers.ProviderInput):
    ensure_provider_idle()
    return providers.save(role, payload)


@api.post('/settings/providers/{role}/test')
async def test_provider(role: providers.Role):
    try:
        return await deepseek.check_provider(role)
    except deepseek.ClientSetupError as exc:
        raise HTTPException(422, str(exc)) from exc


@api.get('/web-resources/search')
async def search_web_resources(q: str = Query(min_length=1, max_length=150), site: web_resources.Site = 'zh'):
    if not q.strip(): raise HTTPException(422, '请输入检索关键词。')
    return await web_resources.search(site, q.strip())


@api.get('/web-resources/preview')
async def preview_web_resource(page_id: int = Query(gt=0), site: web_resources.Site = 'zh'):
    return await web_resources.preview(site, page_id)


@api.post('/web-resources/import', status_code=201)
def import_web_question(payload: web_resources.ImportInput):
    return exam_detail(web_resources.import_question(payload))


@api.get("/courses")
def courses():
    return db.rows("""SELECT c.*,
        (SELECT count(*) FROM documents d WHERE d.course_id=c.id) AS document_count,
        (SELECT count(*) FROM exams e WHERE e.course_id=c.id) AS exam_count,
        (SELECT count(*) FROM questions q JOIN exams e ON q.exam_id=e.id WHERE e.course_id=c.id AND q.is_wrong=1) AS wrong_count
        FROM courses c ORDER BY c.created_at DESC""")


@api.post("/courses", status_code=201)
def create_course(payload: CourseInput):
    if not payload.name.strip():
        raise HTTPException(422, "请输入课程名称。")
    course_id = uuid.uuid4().hex
    db.execute("INSERT INTO courses(id,name,description) VALUES (?,?,?)", (course_id, payload.name.strip(), payload.description.strip()))
    return required("courses", course_id)


@api.put("/courses/{course_id}")
def edit_course(course_id: str, payload: CourseInput):
    required("courses", course_id)
    if not payload.name.strip():
        raise HTTPException(422, "请输入课程名称。")
    db.execute("UPDATE courses SET name=?,description=? WHERE id=?", (payload.name.strip(), payload.description.strip(), course_id))
    return required("courses", course_id)


@api.delete("/courses/{course_id}")
def delete_course(course_id: str):
    required("courses", course_id)
    for plan in db.rows("SELECT id,status FROM exam_plans WHERE course_id=?", (course_id,)):
        if plan['status'] in ('queued', 'running') or plan['id'] in planning.active_plans:
            raise HTTPException(409, "这门课程正在规划，请停止规划并等待当前调用结束后再删除。")
    for exam in db.rows("SELECT id FROM exams WHERE course_id=?", (course_id,)):
        ensure_idle(exam["id"])
    docs = db.rows("SELECT id FROM documents WHERE course_id=?", (course_id,))
    for doc in docs:
        ensure_ocr_idle(doc["id"])
    db.execute("DELETE FROM courses WHERE id=?", (course_id,))
    for doc in docs:
        (db.DATA_DIR / "uploads" / f"{doc['id']}.pdf").unlink(missing_ok=True)
    return {"ok": True}


@api.get("/courses/{course_id}/documents")
def documents(course_id: str):
    required("courses", course_id)
    return [db.decode(d, ("outline", "warnings")) for d in db.rows("""SELECT d.*,
        (SELECT count(*) FROM pages p WHERE p.document_id=d.id AND length(trim(p.text))>=40) AS usable_pages,
        (SELECT count(*) FROM pages p WHERE p.document_id=d.id AND p.ocr_done=1) AS ocr_pages
        FROM documents d WHERE course_id=? ORDER BY created_at DESC""", (course_id,))]


@api.post("/courses/{course_id}/documents", status_code=201)
async def upload_document(course_id: str, file: UploadFile = File(...), kind: str = Form("教材")):
    required("courses", course_id)
    if kind not in ("教材", "习题集", "往年试卷", "个人笔记"):
        raise HTTPException(422, "不支持的资料类型。")
    document_id = uuid.uuid4().hex
    name = (file.filename or "教材.pdf").replace("\\", "/").split("/")[-1][:180]
    path = db.DATA_DIR / "uploads" / f"{document_id}.pdf"
    committed = False
    try:
        file.file.seek(0)
        is_pdf = file.file.read(1024).lstrip().startswith(b"%PDF-")
        file.file.seek(0)
        if is_pdf and file.size is not None and file.size > limits.MAX_PDF_BYTES:
            raise HTTPException(413, f"PDF 不能超过 {limits.MAX_PDF_MB} MB。")
        pages, outline, warnings = await run_in_threadpool(save_and_extract_pdf if is_pdf else save_image_as_pdf, file.file, path)
        # A long-running upload must not recreate a course deleted in another tab.
        required("courses", course_id)
        with db.connection() as con:
            con.execute("INSERT INTO documents(id,course_id,name,kind,page_count,outline,warnings) VALUES (?,?,?,?,?,?,?)",
                (document_id, course_id, name, kind, len(pages), db.dump(outline), db.dump(warnings)))
            con.executemany("INSERT INTO pages(document_id,number,text,warning) VALUES (?,?,?,?)",
                [(document_id, p["number"], p["text"], p["warning"]) for p in pages])
        committed = True
    except PDFSizeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except PDFError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()
        if not committed:
            path.unlink(missing_ok=True)
    return db.decode(required("documents", document_id), ("outline", "warnings"))


@api.get("/documents/{document_id}/file")
def document_file(document_id: str):
    doc = required("documents", document_id)
    return FileResponse(db.DATA_DIR / "uploads" / f"{document_id}.pdf", media_type="application/pdf", filename=doc["name"] if doc["name"].lower().endswith(".pdf") else doc["name"]+".pdf", content_disposition_type="inline")


@api.get("/documents/{document_id}/pages/{number}")
def document_page(document_id: str, number: int):
    page = db.one("SELECT * FROM pages WHERE document_id=? AND number=?", (document_id, number))
    if not page:
        raise HTTPException(404, "页面不存在。")
    return {**page, **materials.page_info(page),
            "text_source": "manual" if page["edited"] else "ocr" if page["ocr_done"] else "pdf",
            "text_quality_issue": text_quality_issue(page["text"])}


@api.put("/documents/{document_id}/pages/{number}")
def update_page(document_id: str, number: int, payload: PageInput):
    document_page(document_id, number)
    db.execute("UPDATE pages SET text=?,edited=1,table_reviewed=0,warning=? WHERE document_id=? AND number=?",
        (payload.text, "文本较少，请确认有足够内容用于出题。" if len(payload.text.strip()) < 40 else "", document_id, number))
    return document_page(document_id, number)


@api.put("/documents/{document_id}/pages/{number}/table-review")
def review_table(document_id: str, number: int, payload: TableReviewInput):
    page = document_page(document_id, number)
    if page["text_hash"] != payload.text_hash:
        raise HTTPException(409, "页面已变化，请重新核对。")
    if payload.confirmed and materials.table_info(page["text"], flagged=True)["table_issues"]:
        raise HTTPException(422, "请先修正表格结构或无法辨认的数据，再确认。")
    with db.connection() as con:
        changed = con.execute("UPDATE pages SET table_flag=1,table_reviewed=? WHERE document_id=? AND number=? AND text=?",
            (int(payload.confirmed), document_id, number, page["text"])).rowcount
    if not changed:
        raise HTTPException(409, "页面已变化，请重新核对。")
    return document_page(document_id, number)


@api.post("/documents/{document_id}/pages/{number}/recognize-region")
async def recognize_region(document_id: str, number: int, payload: RegionInput):
    document_page(document_id, number)
    ensure_ocr_idle(document_id)
    usage_token = ocr._usage_context.set(('document', document_id, f'ocr_region:{number}', 1))
    force_token = ocr._force.set(True)
    try:
        image = await run_in_threadpool(ocr.render_page, db.DATA_DIR / "uploads" / f"{document_id}.pdf", number, payload.model_dump())
        result, tokens_used = await ocr.recognize_page(image)
    except ocr.OCRError as exc:
        raise HTTPException(422, f"{exc}（本次报告用量 {exc.tokens} tokens）") from exc
    finally:
        ocr._usage_context.reset(usage_token)
        ocr._force.reset(force_token)
    return {"usage": usage.summary('document', document_id), "text": result.text, "tokens": tokens_used, "message": "局部识别草稿，未覆盖页面。请核对后手动合并到页面文本。"}


@api.delete("/documents/{document_id}")
def delete_document(document_id: str):
    doc = required("documents", document_id)
    ensure_ocr_idle(document_id)
    for exam in db.rows("SELECT config FROM exams WHERE course_id=?", (doc["course_id"],)):
        if any(r["document_id"] == document_id for r in json.loads(exam["config"])["ranges"]):
            raise HTTPException(409, "这份资料已被试卷引用。为保留来源和重试能力，请先删除相关试卷。")
    db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    (db.DATA_DIR / "uploads" / f"{document_id}.pdf").unlink(missing_ok=True)
    return {"ok": True}


def ensure_ocr_idle(document_id):
    if ocr.is_busy(document_id):
        raise HTTPException(409, "这份资料正在识别，请等待完成或停止识别后再删除。")


@api.get("/documents/{document_id}/pages/{number}/image")
def page_image(document_id: str, number: int):
    document_page(document_id, number)
    try:
        data = ocr.render_page(db.DATA_DIR / "uploads" / f"{document_id}.pdf", number)
    except ocr.OCRError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(data, media_type="image/jpeg")


@api.get("/documents/{document_id}/ocr")
def latest_ocr(document_id: str):
    required("documents", document_id)
    job = db.one("SELECT id FROM ocr_jobs WHERE document_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (document_id,))
    return ocr.detail(job["id"]) if job else None


@api.post("/documents/{document_id}/ocr", status_code=201)
async def start_ocr(document_id: str, payload: OCRInput, background: BackgroundTasks):
    doc = required("documents", document_id)
    if payload.end < payload.start or payload.end > doc["page_count"]:
        raise HTTPException(422, "OCR 页码范围无效，请使用 PDF 实际页码。")
    if payload.end - payload.start + 1 > ocr.MAX_PAGES:
        raise HTTPException(422, f"每次最多识别 {ocr.MAX_PAGES} 页，请分批选择。")
    if not providers.has_key("vision"):
        raise HTTPException(422, "请先在设置中配置 AI API Key。")
    request_hash = drafts.digest({'document_id':document_id, **payload.model_dump(exclude={'submission_id'})})
    job_id = uuid.uuid4().hex
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if payload.submission_id:
            existing = con.execute('SELECT id,request_hash FROM ocr_jobs WHERE submission_id=?', (payload.submission_id,)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash:
                    raise HTTPException(409, '相同识别提交标识不能用于不同资料或设置。')
                return ocr.detail(existing['id'])
        if con.execute("SELECT 1 FROM ocr_jobs WHERE status IN ('queued','running','cancelling')").fetchone():
            raise HTTPException(409, "已有文字识别任务正在进行，请等待完成或停止后再开始。")
        con.execute("INSERT INTO ocr_jobs(id,document_id,start,end,force,token_budget,submission_id,request_hash) VALUES (?,?,?,?,?,?,?,?)",
            (job_id, document_id, payload.start, payload.end, payload.force, payload.token_budget, payload.submission_id, request_hash))
        con.executemany("INSERT INTO ocr_job_pages(job_id,number) VALUES (?,?)", [(job_id, n) for n in range(payload.start, payload.end + 1)])
    background.add_task(ocr.run_job, job_id)
    return ocr.detail(job_id)


@api.get("/ocr/{job_id}")
def get_ocr(job_id: str):
    required("ocr_jobs", job_id)
    return ocr.detail(job_id)


@api.post("/ocr/{job_id}/cancel")
async def cancel_ocr(job_id: str):
    required("ocr_jobs", job_id)
    db.execute("UPDATE ocr_jobs SET status='cancelling' WHERE id=? AND status IN ('queued','running')", (job_id,))
    return ocr.detail(job_id)


@api.put("/ocr/{job_id}/budget")
def update_ocr_budget(job_id: str, payload: OCRBudgetInput):
    job = required('ocr_jobs', job_id)
    if job['status'] in ('queued','running','cancelling'):
        raise HTTPException(409, '请先停止识别后修改预算。')
    db.execute('UPDATE ocr_jobs SET token_budget=? WHERE id=?', (payload.token_budget, job_id))
    return ocr.detail(job_id)


@api.post("/ocr/{job_id}/retry")
async def retry_ocr(job_id: str, background: BackgroundTasks):
    required("ocr_jobs", job_id)
    if ocr.is_busy() or job_id in ocr.active_jobs:
        raise HTTPException(409, "已有文字识别任务正在进行，请稍后重试。")
    if not providers.has_key("vision"):
        raise HTTPException(422, "请先在设置中配置 AI API Key。")
    db.execute("UPDATE ocr_job_pages SET status='pending',error='' WHERE job_id=? AND status NOT IN ('ready','skipped')", (job_id,))
    db.execute("UPDATE ocr_jobs SET status='queued' WHERE id=?", (job_id,))
    background.add_task(ocr.run_job, job_id)
    return ocr.detail(job_id)


def validate_ranges(payload):
    required("courses", payload.course_id)
    for scope in payload.ranges:
        doc = required("documents", scope.document_id)
        if doc["course_id"] != payload.course_id or scope.end > doc["page_count"]:
            raise HTTPException(422, "资料不属于此课程，或页码超出范围。")
    try:
        return retrieve(payload.model_dump())
    except GenerationError as exc:
        raise HTTPException(422, str(exc)) from exc


@api.post("/retrieval-preview")
def retrieval_preview(payload: ExamInput):
    sources = validate_ranges(payload)
    if payload.reading_mode == "vision":
        return {"sources":sources, "excluded":[]}
    _, excluded = material_candidates(payload.model_dump())
    return {"sources": sources, "excluded": excluded}


@api.post("/exam-plans", status_code=201)
async def create_plan(payload: ExamInput, background: BackgroundTasks):
    config = payload.model_dump()
    config.update(plan_id=None, blueprint=[])
    if payload.submission_id:
        existing=db.one('SELECT * FROM exam_plans WHERE submission_id=?',(payload.submission_id,))
        if existing:
            if drafts.clean_config(json.loads(existing['config'])) != drafts.clean_config(config):
                raise HTTPException(409,'同一规划提交标识不能用于不同设置。')
            return planning.detail(existing['id'])
    validate_ranges(payload)
    if payload.parent_plan_id:
        parent=required('exam_plans',payload.parent_plan_id)
        if parent['course_id']!=payload.course_id: raise HTTPException(422,'原规划不属于此课程。')
    try:
        refs, excluded = planning.prepare(config)
    except GenerationError as exc:
        raise HTTPException(422, str(exc)) from exc
    plan_id = uuid.uuid4().hex
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if payload.submission_id:
            existing=con.execute('SELECT id,config FROM exam_plans WHERE submission_id=?',(payload.submission_id,)).fetchone()
            if existing:
                if drafts.clean_config(json.loads(existing['config'])) != drafts.clean_config(config): raise HTTPException(409,'同一规划提交标识不能用于不同设置。')
                return planning.detail(existing['id'])
        if con.execute("SELECT 1 FROM exam_plans WHERE status IN ('queued','running')").fetchone():
            raise HTTPException(409,'已有考点规划正在进行，请继续上次规划查看进度。')
        con.execute("INSERT INTO exam_plans(id,course_id,config,fingerprint,materials,excluded,manifest,parent_id,submission_id,updated_at) VALUES (?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (plan_id,payload.course_id,db.dump(config),planning.fingerprint(config,refs),db.dump(refs),db.dump(excluded),db.dump(drafts.source_manifest(config)),payload.parent_plan_id,payload.submission_id))
    background.add_task(planning.run_plan, plan_id)
    return planning.detail(plan_id)


@api.get('/courses/{course_id}/exam-plans/latest')
def latest_plan(course_id: str):
    required('courses',course_id)
    row=db.one('SELECT id FROM exam_plans WHERE course_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 1',(course_id,))
    return planning.detail(row['id']) if row else None


@api.put('/exam-plans/{plan_id}/draft')
def save_plan(plan_id: str, payload: PlanSaveInput):
    drafts.save(plan_id,payload)
    return planning.detail(plan_id)


@api.get('/exam-plans/{plan_id}/history')
def plan_history(plan_id: str):
    required('exam_plans',plan_id)
    return drafts.history(plan_id)


@api.post("/exam-plans/{plan_id}/cancel")
def cancel_plan(plan_id: str):
    required("exam_plans", plan_id)
    db.execute("UPDATE exam_plans SET status='cancelled' WHERE id=? AND status IN ('queued','running')", (plan_id,))
    return planning.detail(plan_id)


@api.get("/exam-plans/{plan_id}")
def get_plan(plan_id: str):
    result = planning.detail(plan_id)
    if not result:
        raise HTTPException(404, "规划不存在。")
    return result


@api.post("/exams", status_code=201)
async def create_exam(payload: ExamInput, background: BackgroundTasks):
    request_hash=drafts.digest({k:v for k,v in payload.model_dump().items() if k not in ('submission_id','parent_plan_id')})
    keys=[]
    if payload.submission_id: keys.append('request:'+payload.submission_id)
    if payload.plan_id: keys.append('plan:'+payload.plan_id)
    exam_id=uuid.uuid4().hex
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        for key in keys:
            existing=con.execute('SELECT * FROM exam_submissions WHERE key=?',(key,)).fetchone()
            if existing:
                if existing['request_hash']!=request_hash:
                    raise HTTPException(409,'这份规划或提交标识已用于另一份设置，请查看原试卷，或新建规划。')
                if not con.execute('SELECT 1 FROM exams WHERE id=?',(existing['exam_id'],)).fetchone():
                    raise HTTPException(410,'原试卷已删除；不会重复创建，请新建规划。')
                return exam_detail(existing['exam_id'])
        validate_ranges(payload)
        if not providers.has_key('vision' if payload.reading_mode == 'vision' else 'text'): raise HTTPException(422,'请先在设置中配置 AI API Key。')
        try: planning.validate_blueprint(payload)
        except GenerationError as exc: raise HTTPException(422,str(exc)) from exc
        if con.execute("SELECT 1 FROM exams WHERE status IN ('queued','generating')").fetchone():
            raise HTTPException(409,'已有试卷正在生成，请等待完成后再创建。')
        con.execute('INSERT INTO exams(id,course_id,title,config) VALUES (?,?,?,?)',(exam_id,payload.course_id,payload.title,db.dump(payload.model_dump())))
        for index, rule in enumerate(payload.blueprint or plan_questions(payload),1):
            con.execute('INSERT INTO questions(id,exam_id,position,type,points) VALUES (?,?,?,?,?)',(uuid.uuid4().hex,exam_id,index,rule.type,rule.points))
        for key in keys:
            con.execute('INSERT INTO exam_submissions(key,request_hash,exam_id) VALUES (?,?,?)',(key,request_hash,exam_id))
    background.add_task(run_generation,exam_id)
    return exam_detail(exam_id)


@api.get("/exams")
def exams(course_id: str = ""):
    return db.rows("""SELECT e.*,c.name AS course_name,
        (SELECT count(*) FROM questions q WHERE q.exam_id=e.id) AS question_count,
        (SELECT count(*) FROM questions q WHERE q.exam_id=e.id AND q.status='ready') AS ready_count,
        (SELECT coalesce(sum(points),0) FROM questions q WHERE q.exam_id=e.id) AS total_points
        FROM exams e JOIN courses c ON c.id=e.course_id WHERE (?='' OR e.course_id=?) ORDER BY e.created_at DESC""", (course_id, course_id))


@api.get("/exams/{exam_id}")
def get_exam(exam_id: str):
    return exam_detail(exam_id)


@api.post("/exams/{exam_id}/pause")
async def pause_exam(exam_id: str):
    required("exams", exam_id)
    db.execute("UPDATE exams SET status='paused' WHERE id=? AND status IN ('queued','generating')", (exam_id,))
    return {"ok": True, "message": "当前调用结束后暂停，已完成的题目会保留。"}


@api.put("/exams/{exam_id}/budget")
def update_budget(exam_id: str, payload: BudgetInput):
    exam = ensure_idle(exam_id)
    config = json.loads(exam['config'])
    config.update(payload.model_dump())
    db.execute('UPDATE exams SET config=? WHERE id=?',(db.dump(config),exam_id))
    return exam_detail(exam_id)


@api.post("/questions/{question_id}/explanation")
async def expand_explanation(question_id: str):
    question = required('questions',question_id)
    exam = ensure_idle(question['exam_id'])
    if json.loads(exam['config']).get('origin') == 'web_import':
        raise HTTPException(422, '来源摘录题不支持重新生成或 AI 详解；可手动编辑修订。')
    if question['status'] != 'ready': raise HTTPException(409,'请先完成题目生成。')
    if not providers.has_key('vision' if json.loads(exam['config']).get('reading_mode') == 'vision' else 'text'): raise HTTPException(422,'请先配置 AI API Key。')
    active_exams.add(exam['id'])
    try:
        await explanations.expand(question,exam)
    except (GenerationError,deepseek.ClientSetupError) as exc:
        raise HTTPException(422,str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422,'补充详解失败，原解析已保留；已报告用量已记录。') from exc
    finally:
        active_exams.discard(exam['id'])
    return db.question(required('questions',question_id))


@api.post("/exams/{exam_id}/retry")
async def retry_exam(exam_id: str, background: BackgroundTasks):
    exam = ensure_idle(exam_id)
    if not providers.has_key("vision" if json.loads(exam["config"]).get("reading_mode") == "vision" else "text"):
        raise HTTPException(422, "请先配置 AI API Key。")
    if json.loads(exam['config']).get('origin') == 'web_import':
        raise HTTPException(422, '来源摘录题不支持重新生成或 AI 详解；可手动编辑修订。')
    validate_ranges(ExamInput.model_validate_json(exam["config"]))
    config=json.loads(exam['config'])
    if config.get('token_budget') and exam['tokens'] >= config['token_budget']:
        raise HTTPException(422,'已达到 token 预算阈值，请先调整预算。')
    pending = db.one("SELECT count(*) AS n FROM questions WHERE exam_id=? AND status!='ready'", (exam_id,))["n"]
    if not pending:
        return exam_detail(exam_id)
    db.execute("UPDATE questions SET status='pending',error='' WHERE exam_id=? AND status!='ready'", (exam_id,))
    db.execute("UPDATE exams SET status='queued',error='' WHERE id=?", (exam_id,))
    background.add_task(run_generation, exam_id)
    return exam_detail(exam_id)


@api.delete("/exams/{exam_id}")
def delete_exam(exam_id: str):
    ensure_idle(exam_id)
    db.execute("DELETE FROM exams WHERE id=?", (exam_id,))
    return {"ok": True}


@api.post("/questions/{question_id}/regenerate")
async def regenerate(question_id: str, background: BackgroundTasks):
    question = required("questions", question_id)
    exam = ensure_idle(question["exam_id"])
    if not providers.has_key("vision" if json.loads(exam["config"]).get("reading_mode") == "vision" else "text"):
        raise HTTPException(422, "请先配置 AI API Key。")
    if json.loads(exam['config']).get('origin') == 'web_import':
        raise HTTPException(422, '来源摘录题不支持重新生成或 AI 详解；可手动编辑修订。')
    validate_ranges(ExamInput.model_validate_json(exam["config"]))
    db.execute("UPDATE questions SET candidate='',status='pending',error='' WHERE id=?", (question_id,))
    db.execute("UPDATE exams SET status='queued',error='' WHERE id=?", (question["exam_id"],))
    background.add_task(run_generation, question["exam_id"])
    return {"ok": True}


def refresh_exam(exam_id):
    incomplete = db.one("SELECT count(*) AS n FROM questions WHERE exam_id=? AND status!='ready'", (exam_id,))["n"]
    db.execute("UPDATE exams SET status=?,error='' WHERE id=?", ("partial" if incomplete else "ready", exam_id))


@api.put("/questions/{question_id}")
def edit_question(question_id: str, payload: QuestionEdit):
    question = required("questions", question_id)
    exam = ensure_idle(question["exam_id"])
    config = json.loads(exam["config"])
    refs = json.loads(question["sources"]) if config.get("origin") == "web_import" else []
    for scope in config["ranges"]:
        doc = required("documents", scope["document_id"])
        refs.extend({"document_id": doc["id"], "page": n, "name": doc["name"]} for n in range(scope["start"], scope["end"]+1))
    try:
        checked = validate_content(payload.model_dump(), question["type"], refs, [])
    except GenerationError as exc:
        raise HTTPException(422, str(exc)) from exc
    names = {(r["document_id"], r["page"]): r["name"] for r in refs}
    sources = [{**s.model_dump(), "name": names[(s.document_id, s.page)]} for s in payload.sources]
    if config.get('origin') == 'web_import':
        # Attribution is immutable through the manual question editor.
        sources = [{**s, 'modified': True} for s in json.loads(question['sources'])]
    db.execute("""UPDATE questions SET candidate='',stem=?,options=?,answer=?,explanation=?,rubric=?,knowledge=?,sources=?,blanks=?,review='{}',points=?,status='ready',error='',self_score=NULL,is_wrong=0 WHERE id=?""",
        (payload.stem, db.dump(payload.options), checked.answer, payload.explanation, db.dump(payload.rubric), payload.knowledge, db.dump(sources), db.dump([b.model_dump() for b in checked.blanks]), payload.points, question_id))
    refresh_exam(question["exam_id"])
    return db.question(required("questions", question_id))


@api.delete("/questions/{question_id}")
def delete_question(question_id: str):
    question = required("questions", question_id)
    ensure_idle(question["exam_id"])
    count = db.one("SELECT count(*) AS n FROM questions WHERE exam_id=?", (question["exam_id"],))["n"]
    if count <= 1:
        raise HTTPException(422, "试卷至少保留一道题；如不需要可删除整份试卷。")
    db.execute("DELETE FROM questions WHERE id=?", (question_id,))
    refresh_exam(question["exam_id"])
    return {"ok": True}


@api.post('/questions/{question_id}/check-answer')
def check_answer(question_id: str, payload: AnswerCheckInput):
    question=db.question(required('questions',question_id))
    if question['status']!='ready': raise HTTPException(409,'请等待题目生成完成。')
    try: return answer_check.check(question,payload)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc


@api.patch("/questions/{question_id}/progress")
def progress(question_id: str, payload: ProgressInput):
    values = payload.model_dump(exclude_unset=True)
    auto_score = values.pop('auto_score', False)
    checked = None
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
        if not row:
            raise HTTPException(404, '题目不存在。')
        question = dict(row)
        if question['status'] != 'ready':
            raise HTTPException(409, '请等待此题生成完成后再作答。')
        if auto_score:
            if values.get('user_answer') is None or 'self_score' in values or 'is_wrong' in values:
                raise HTTPException(422, '自动评分需提交作答，不能同时指定分数或错题状态。')
            try:
                if question['type'] in MULTI_TYPES:
                    values['user_answer'] = canonical(values['user_answer'])
                checked = answer_check.check_saved_answer(db.question(dict(question)), values['user_answer'])
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            # An entirely blank answer is saved as ungraded, not a zero-point attempt.
            values['self_score'] = checked['suggested_score'] if any(item['status'] != 'empty' for item in checked['items']) else None
        if values.get('self_score') is not None:
            if values['self_score'] > question['points']:
                raise HTTPException(422, '自评分不能超过本题分值。')
            if 'is_wrong' not in values:
                values['is_wrong'] = values['self_score'] < question['points']
        values = {k: v for k, v in values.items() if v is not None or k == 'self_score'}
        unchanged_auto_score = auto_score and values.get('user_answer') == question['user_answer'] and values.get('self_score') == question['self_score']
        if values.get('self_score') is not None and not unchanged_auto_score:
            con.execute('INSERT INTO attempts(id,question_id,user_answer,score,snapshot) VALUES (?,?,?,?,?)',
                (uuid.uuid4().hex, question_id, values.get('user_answer', question['user_answer']), values['self_score'], db.dump(db.question(dict(question)))))
        if values:
            con.execute(f"UPDATE questions SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), question_id))
        saved = db.question(dict(con.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()))
    return {**saved, 'answer_check': checked}



@api.get("/questions/{question_id}/attempts")
def attempts(question_id: str):
    required("questions", question_id)
    return [db.decode(r, ("snapshot",)) for r in db.rows("SELECT * FROM attempts WHERE question_id=? ORDER BY created_at DESC", (question_id,))]


@api.get("/review")
def review(course_id: str = "", mode: str = "wrong"):
    condition = "q.is_favorite=1" if mode == "favorites" else "q.is_wrong=1"
    return [db.question(q) for q in db.rows(f"""SELECT q.*,e.title AS exam_title,e.course_id,c.name AS course_name
        FROM questions q JOIN exams e ON e.id=q.exam_id JOIN courses c ON c.id=e.course_id
        WHERE {condition} AND (?='' OR e.course_id=?) ORDER BY e.created_at DESC,q.position""", (course_id, course_id))]


app.include_router(api)

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "接口不存在。")
    if not (DIST / "index.html").exists():
        return JSONResponse({"message": "前端尚未构建。请在 frontend 目录运行 npm install 和 npm run build。"}, status_code=503)
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
