import asyncio
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend import db, generation, security
from backend.main import app
from backend.models import GeneratedQuestion


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 780 Td (Probability: independent events satisfy P[A and B] = P[A] * P[B].) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_outline_item("Probability", 0)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setenv("STUDY_ACCESS_CODE", "test-access-123")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    security.failures.clear()
    generation.active_exams.clear()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def setup(client):
    assert client.post("/api/login", json={"code": "test-access-123"}).status_code == 200
    course = client.post("/api/courses", json={"name": "概率论"}).json()
    doc = client.post(f"/api/courses/{course['id']}/documents", files={"file": ("probability.pdf", sample_pdf(), "application/pdf")}).json()
    client.put("/api/settings", json={"api_key": "test-key-never-send", "model": "deepseek-chat"})
    return course, doc


def exam_config(setup, count=2):
    course, doc = setup
    return {"course_id": course["id"], "title": "概率论测试", "ranges": [{"document_id": doc["id"], "start": 1, "end": 1}],
        "rules": [{"type": "calculation", "count": count, "points": 10}], "difficulty": "基础巩固"}


async def fake_generate(question, config, references, previous):
    return GeneratedQuestion(stem=f"第 {question['position']} 个练习：设两个事件独立，求概率。", options=[], answer="$0.25$",
        explanation="由独立事件的乘法公式计算。", rubric=["写出公式 5 分", "正确计算 5 分"], knowledge="事件独立性",
        sources=[{"document_id": references[0]["document_id"], "page": references[0]["page"]}]), 100


def test_auth_and_origin(client):
    assert client.get("/api/courses").status_code == 401
    assert client.post("/api/login", json={"code": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"code": "test-access-123"}, headers={"Origin": "https://evil.example"}).status_code == 403
    response = client.post("/api/login", json={"code": "test-access-123"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/settings").status_code == 401


def test_pdf_preview_correction_and_key_privacy(client, setup):
    course, doc = setup
    assert doc["page_count"] == 1
    assert doc["outline"][0]["page"] == 1
    page = client.get(f"/api/documents/{doc['id']}/pages/1").json()
    assert "Probability" in page["text"]
    fixed = client.put(f"/api/documents/{doc['id']}/pages/1", json={"text": "独立事件：$P(A\\cap B)=P(A)P(B)$。" * 5}).json()
    assert fixed["edited"] == 1
    assert "test-key-never-send" not in client.get("/api/settings").text
    assert client.get("/api/settings").json()["has_key"] is True
    assert client.post(f"/api/courses/{course['id']}/documents", files={"file": ("bad.pdf", b"not pdf")}).status_code == 422
    assert client.get(f"/api/documents/{doc['id']}/file").content.startswith(b"%PDF")


def test_scope_isolation_and_insufficient_text(client, setup):
    config = exam_config(setup)
    config["ranges"][0]["end"] = 2
    assert client.post("/api/retrieval-preview", json=config).status_code == 422
    config["ranges"][0]["end"] = 1
    config["course_id"] = client.post("/api/courses", json={"name": "离散数学"}).json()["id"]
    assert client.post("/api/retrieval-preview", json=config).status_code == 422
    config["course_id"] = setup[0]["id"]
    client.put(f"/api/documents/{setup[1]['id']}/pages/1", json={"text": ""})
    assert client.post("/api/exams", json=config).status_code == 422


def test_full_generation_scoring_and_history(client, setup, monkeypatch):
    monkeypatch.setattr(generation, "generate_one", fake_generate)
    response = client.post("/api/exams", json=exam_config(setup))
    assert response.status_code == 201
    exam = client.get(f"/api/exams/{response.json()['id']}").json()
    assert exam["status"] == "ready"
    assert exam["tokens"] == 200 and exam["total_points"] == 20
    q = exam["questions"][0]
    assert q["sources"][0]["page"] == 1
    assert client.patch(f"/api/questions/{q['id']}/progress", json={"self_score": 11}).status_code == 422
    saved = client.patch(f"/api/questions/{q['id']}/progress", json={"user_answer": "纸上完成", "self_score": 6, "is_favorite": True}).json()
    assert saved["is_wrong"] == 1
    assert len(client.get("/api/review").json()) == 1
    assert len(client.get("/api/review?mode=favorites").json()) == 1
    history = client.get(f"/api/questions/{q['id']}/attempts").json()
    assert history[0]["score"] == 6 and history[0]["snapshot"]["answer"] == "$0.25$"
    assert client.delete(f"/api/documents/{setup[1]['id']}").status_code == 409
    assert client.post(f"/api/questions/{q['id']}/regenerate").status_code == 200
    regenerated = client.get(f"/api/exams/{exam['id']}").json()["questions"][0]
    assert regenerated["self_score"] is None
    assert len(client.get(f"/api/questions/{q['id']}/attempts").json()) == 1


def test_partial_failure_retry_preserves_completed_questions(client, setup, monkeypatch):
    async def flaky(question, *args):
        if question["position"] == 2:
            raise generation.GenerationError("题目格式有误，请重试。")
        return await fake_generate(question, *args)
    monkeypatch.setattr(generation, "generate_one", flaky)
    exam_id = client.post("/api/exams", json=exam_config(setup)).json()["id"]
    before = client.get(f"/api/exams/{exam_id}").json()
    assert before["status"] == "partial"
    assert [q["status"] for q in before["questions"]] == ["ready", "failed"]
    monkeypatch.setattr(generation, "generate_one", fake_generate)
    assert client.post(f"/api/exams/{exam_id}/retry").status_code == 200
    after = client.get(f"/api/exams/{exam_id}").json()
    assert after["status"] == "ready"
    assert before["questions"][0] == after["questions"][0]


def test_restart_marks_pending_without_losing_content(client, setup, monkeypatch):
    monkeypatch.setattr(generation, "generate_one", fake_generate)
    exam_id = client.post("/api/exams", json=exam_config(setup)).json()["id"]
    db.execute("UPDATE exams SET status='generating' WHERE id=?", (exam_id,))
    db.execute("UPDATE questions SET status='pending' WHERE exam_id=? AND position=2", (exam_id,))
    db.init_db()
    exam = client.get(f"/api/exams/{exam_id}").json()
    assert exam["status"] == "partial"
    assert exam["questions"][0]["status"] == "ready"
    assert exam["questions"][1]["status"] == "failed"


def test_question_edit_delete_and_score_reset(client, setup, monkeypatch):
    monkeypatch.setattr(generation, "generate_one", fake_generate)
    exam_id = client.post("/api/exams", json=exam_config(setup)).json()["id"]
    q = client.get(f"/api/exams/{exam_id}").json()["questions"][0]
    client.patch(f"/api/questions/{q['id']}/progress", json={"self_score": 10})
    q["stem"] = "修改后的数学题：计算两个独立事件的交集概率。"
    q["points"] = 5
    edited = client.put(f"/api/questions/{q['id']}", json=q).json()
    assert edited["points"] == 5 and edited["self_score"] is None
    assert client.delete(f"/api/questions/{q['id']}").status_code == 200
    remaining = client.get(f"/api/exams/{exam_id}").json()["questions"][0]
    assert client.delete(f"/api/questions/{remaining['id']}").status_code == 422


def test_random_plan_bounds_and_invalid_counts(client, setup, monkeypatch):
    monkeypatch.setattr(generation, "generate_one", fake_generate)
    config = exam_config(setup)
    config.update(mode="random", random_count=3)
    exam_id = client.post("/api/exams", json=config).json()["id"]
    assert len(client.get(f"/api/exams/{exam_id}").json()["questions"]) == 3
    config.update(mode="custom", rules=[{"type": "proof", "count": 0, "points": 10}])
    assert client.post("/api/exams", json=config).status_code == 422


def valid_payload():
    return {"stem": "若两个事件相互独立，下列结论哪一个成立？", "options": ["第一项", "第二项", "第三项", "第四项"],
        "answer": "A", "explanation": "根据独立事件定义。", "rubric": ["选择正确得满分"], "knowledge": "独立性",
        "sources": [{"document_id": "doc", "page": 1}]}


@pytest.mark.parametrize("mutation", ["bad_citation", "multiple_answers", "duplicate", "bad_options"])
def test_generated_content_validation(mutation):
    payload = valid_payload()
    previous = []
    if mutation == "bad_citation": payload["sources"][0]["page"] = 99
    if mutation == "multiple_answers": payload["answer"] = "AB"
    if mutation == "duplicate": previous = [payload["stem"]]
    if mutation == "bad_options": payload["options"] = ["same"] * 4
    with pytest.raises(generation.GenerationError):
        generation.validate_content(payload, "choice", [{"document_id": "doc", "page": 1}], previous)


def test_real_provider_adapter_uses_structured_json(client, setup, monkeypatch):
    original = httpx.AsyncClient
    payload = valid_payload()
    def handler(request):
        assert request.url == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert request.headers["authorization"] == "Bearer test-key-never-send"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}], "usage": {"total_tokens": 234}})
    monkeypatch.setattr(generation.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    question, usage = asyncio.run(generation.generate_one({"type": "choice", "points": 5}, {"difficulty": "基础巩固"}, [{"document_id": "doc", "page": 1}], []))
    assert question.answer == "A" and usage == 234


def test_provider_failure_hides_response_body(client, setup, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(generation.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(lambda req: httpx.Response(401, text="secret-provider-body")), **kw))
    with pytest.raises(generation.GenerationError, match="密钥无效") as exc:
        asyncio.run(generation.generate_one({"type": "choice", "points": 5}, {"difficulty": "基础巩固"}, [], []))
    assert "secret-provider-body" not in str(exc.value)


def test_unicode_access_code_and_rate_limit(client, monkeypatch):
    monkeypatch.setenv("STUDY_ACCESS_CODE", "数学学习-我的口令123")
    assert client.post("/api/login", json={"code": "数学学习-我的口令123"}).status_code == 200
    for _ in range(10):
        assert client.post("/api/login", json={"code": "错误口令"}).status_code == 401
    assert client.post("/api/login", json={"code": "数学学习-我的口令123"}).status_code == 429


def test_restart_practice_preserves_wrong_mark_and_history(client, setup, monkeypatch):
    monkeypatch.setattr(generation, "generate_one", fake_generate)
    exam_id = client.post("/api/exams", json=exam_config(setup, count=1)).json()["id"]
    q = client.get(f"/api/exams/{exam_id}").json()["questions"][0]
    client.patch(f"/api/questions/{q['id']}/progress", json={"self_score": 3, "user_answer": "旧答案"})
    result = client.patch(f"/api/questions/{q['id']}/progress", json={"self_score": None, "user_answer": ""}).json()
    assert result["self_score"] is None and result["user_answer"] == ""
    assert result["is_wrong"] == 1
    assert len(client.get(f"/api/questions/{q['id']}/attempts").json()) == 1
