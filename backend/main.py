import asyncio
import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, security
from .generation import GenerationError, active_exams, plan_questions, retrieve, run_generation, validate_content
from .models import CourseInput, ExamInput, LoginInput, PageInput, ProgressInput, QuestionEdit, SettingsInput
from .pdf import PDFError, extract_pdf


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    security.initialize_access()
    yield


app = FastAPI(title="知习 · AI 学习助手", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


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
    exam["total_points"] = sum(q["points"] for q in exam["questions"])
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
    return {"has_key": bool(security.api_key()), "key_from_env": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "model": db.setting("model", "deepseek-chat")}


@api.put("/settings")
def update_settings(payload: SettingsInput):
    if payload.clear_key:
        db.set_setting("api_key", "")
    elif payload.api_key.strip():
        db.set_setting("api_key", payload.api_key.strip())
    db.set_setting("model", payload.model)
    return settings()


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
    for exam in db.rows("SELECT id FROM exams WHERE course_id=?", (course_id,)):
        ensure_idle(exam["id"])
    docs = db.rows("SELECT id FROM documents WHERE course_id=?", (course_id,))
    db.execute("DELETE FROM courses WHERE id=?", (course_id,))
    for doc in docs:
        (db.DATA_DIR / "uploads" / f"{doc['id']}.pdf").unlink(missing_ok=True)
    return {"ok": True}


@api.get("/courses/{course_id}/documents")
def documents(course_id: str):
    required("courses", course_id)
    return [db.decode(d, ("outline", "warnings")) for d in db.rows("SELECT * FROM documents WHERE course_id=? ORDER BY created_at DESC", (course_id,))]


@api.post("/courses/{course_id}/documents", status_code=201)
async def upload_document(course_id: str, file: UploadFile = File(...), kind: str = Form("教材")):
    required("courses", course_id)
    if kind not in ("教材", "习题集", "往年试卷", "个人笔记"):
        raise HTTPException(422, "不支持的资料类型。")
    data = await file.read(30 * 1024 * 1024 + 1)
    await file.close()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(413, "PDF 不能超过 30 MB。")
    try:
        pages, outline, warnings = await asyncio.to_thread(extract_pdf, data)
    except PDFError as exc:
        raise HTTPException(422, str(exc)) from exc
    document_id = uuid.uuid4().hex
    name = (file.filename or "教材.pdf").replace("\\", "/").split("/")[-1][:180]
    path = db.DATA_DIR / "uploads" / f"{document_id}.pdf"
    try:
        path.write_bytes(data)
        path.chmod(0o600)
        with db.connection() as con:
            con.execute("INSERT INTO documents(id,course_id,name,kind,page_count,outline,warnings) VALUES (?,?,?,?,?,?,?)",
                (document_id, course_id, name, kind, len(pages), db.dump(outline), db.dump(warnings)))
            con.executemany("INSERT INTO pages(document_id,number,text,warning) VALUES (?,?,?,?)",
                [(document_id, p["number"], p["text"], p["warning"]) for p in pages])
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return db.decode(required("documents", document_id), ("outline", "warnings"))


@api.get("/documents/{document_id}/file")
def document_file(document_id: str):
    doc = required("documents", document_id)
    return FileResponse(db.DATA_DIR / "uploads" / f"{document_id}.pdf", media_type="application/pdf", filename=doc["name"], content_disposition_type="inline")


@api.get("/documents/{document_id}/pages/{number}")
def document_page(document_id: str, number: int):
    page = db.one("SELECT * FROM pages WHERE document_id=? AND number=?", (document_id, number))
    if not page:
        raise HTTPException(404, "页面不存在。")
    return page


@api.put("/documents/{document_id}/pages/{number}")
def update_page(document_id: str, number: int, payload: PageInput):
    document_page(document_id, number)
    db.execute("UPDATE pages SET text=?,edited=1,warning=? WHERE document_id=? AND number=?",
        (payload.text, "文本较少，请确认有足够内容用于出题。" if len(payload.text.strip()) < 40 else "", document_id, number))
    return document_page(document_id, number)


@api.delete("/documents/{document_id}")
def delete_document(document_id: str):
    doc = required("documents", document_id)
    for exam in db.rows("SELECT config FROM exams WHERE course_id=?", (doc["course_id"],)):
        if any(r["document_id"] == document_id for r in json.loads(exam["config"])["ranges"]):
            raise HTTPException(409, "这份资料已被试卷引用。为保留来源和重试能力，请先删除相关试卷。")
    db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    (db.DATA_DIR / "uploads" / f"{document_id}.pdf").unlink(missing_ok=True)
    return {"ok": True}


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
    return {"sources": validate_ranges(payload)}


@api.post("/exams", status_code=201)
async def create_exam(payload: ExamInput, background: BackgroundTasks):
    validate_ranges(payload)
    if not security.api_key():
        raise HTTPException(422, "请先在设置中配置 DeepSeek API Key。")
    # Async route with no await until insert: prevent duplicate scheduling in this process.
    if db.one("SELECT id FROM exams WHERE status IN ('queued','generating')"):
        raise HTTPException(409, "已有试卷正在生成，请等待完成后再创建。")
    exam_id = uuid.uuid4().hex
    with db.connection() as con:
        con.execute("INSERT INTO exams(id,course_id,title,config) VALUES (?,?,?,?)", (exam_id, payload.course_id, payload.title, db.dump(payload.model_dump())))
        for index, rule in enumerate(plan_questions(payload), 1):
            con.execute("INSERT INTO questions(id,exam_id,position,type,points) VALUES (?,?,?,?,?)", (uuid.uuid4().hex, exam_id, index, rule.type, rule.points))
    background.add_task(run_generation, exam_id)
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


@api.post("/exams/{exam_id}/retry")
async def retry_exam(exam_id: str, background: BackgroundTasks):
    exam = ensure_idle(exam_id)
    if not security.api_key():
        raise HTTPException(422, "请先配置 DeepSeek API Key。")
    validate_ranges(ExamInput.model_validate_json(exam["config"]))
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
    if not security.api_key():
        raise HTTPException(422, "请先配置 DeepSeek API Key。")
    validate_ranges(ExamInput.model_validate_json(exam["config"]))
    db.execute("UPDATE questions SET status='pending',error='' WHERE id=?", (question_id,))
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
    refs = []
    for scope in config["ranges"]:
        doc = required("documents", scope["document_id"])
        refs.extend({"document_id": doc["id"], "page": n, "name": doc["name"]} for n in range(scope["start"], scope["end"]+1))
    try:
        validate_content(payload.model_dump(), question["type"], refs, [])
    except GenerationError as exc:
        raise HTTPException(422, str(exc)) from exc
    names = {(r["document_id"], r["page"]): r["name"] for r in refs}
    sources = [{**s.model_dump(), "name": names[(s.document_id, s.page)]} for s in payload.sources]
    db.execute("""UPDATE questions SET stem=?,options=?,answer=?,explanation=?,rubric=?,knowledge=?,sources=?,points=?,status='ready',error='',self_score=NULL,is_wrong=0 WHERE id=?""",
        (payload.stem, db.dump(payload.options), payload.answer, payload.explanation, db.dump(payload.rubric), payload.knowledge, db.dump(sources), payload.points, question_id))
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


@api.patch("/questions/{question_id}/progress")
def progress(question_id: str, payload: ProgressInput):
    question = required("questions", question_id)
    if question["status"] != "ready":
        raise HTTPException(409, "请等待此题生成完成后再作答。")
    values = payload.model_dump(exclude_unset=True)
    if "self_score" in values and values["self_score"] is not None:
        if values["self_score"] > question["points"]:
            raise HTTPException(422, "自评分不能超过本题分值。")
        if "is_wrong" not in values:
            values["is_wrong"] = values["self_score"] < question["points"]
    values = {k: v for k, v in values.items() if v is not None or k == "self_score"}
    with db.connection() as con:
        if values.get("self_score") is not None:
            con.execute("INSERT INTO attempts(id,question_id,user_answer,score,snapshot) VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, question_id, values.get("user_answer", question["user_answer"]), values["self_score"], db.dump(db.question(dict(question)))))
        if values:
            con.execute(f"UPDATE questions SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), question_id))
    return db.question(required("questions", question_id))


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
