"""Explicit test-only server. Never imported by the production launcher.

E2E uses deterministic generated questions without spending API credits.
"""
import asyncio
import os
import tempfile
from pathlib import Path

os.environ["STUDY_ACCESS_CODE"] = "browser-test-only"
os.environ["DEEPSEEK_API_KEY"] = "mock-provider-for-browser-tests"
os.environ["STUDY_DATA_DIR"] = tempfile.mkdtemp(prefix="zhixi-e2e-")

from backend import generation  # noqa: E402
from backend.main import app  # noqa: E402, F401
from backend.models import GeneratedQuestion  # noqa: E402
from tests.test_api import sample_pdf  # noqa: E402

Path(os.environ["STUDY_DATA_DIR"], "sample.pdf").write_bytes(sample_pdf())


async def mock_generate(question, config, references, previous):
    await asyncio.sleep(.05)
    kind = question["type"]
    return GeneratedQuestion(
        blanks=[{"answer":"$0.2$", "alternatives":[]}, {"answer":"0.5", "alternatives":[]}] if kind == "fill" else [],
        stem="独立事件 A、B 的交集概率为 [[blank:1]]，比例为 $v=[[blank:2]] V$。" if kind == "fill" else f"练习 {question['position']}：设事件 $A$ 与 $B$ 相互独立，且 $P(A)=0.4$，$P(B)=0.5$。求 $P(A\\cap B)$。",
        options=["$0.2$", "$0.4$", "$0.5$", "$0.9$"] if kind in ("choice", "multiple_choice", "indefinite_choice") else [],
        answer="AC" if kind in ("multiple_choice", "indefinite_choice") else "A" if kind == "choice" else "正确" if kind == "true_false" else "$P(A\\cap B)=0.2$",
        explanation="由事件独立的定义，有：\n\n$$P(A\\cap B)=P(A)P(B)=0.4\\times0.5=0.2.$$\n\n注意独立与互斥的区别。此处两事件可以同时发生。",
        rubric=["正确写出独立事件的乘法公式。", "正确代入数值并计算。"],
        knowledge=r"事件独立性：$P(A\cap B)=P(A)P(B)$；泊松近似：$\binom{n}{k}p^k(1-p)^{n-k}\approx\frac{\lambda^k e^{-\lambda}}{k!}$，$\lambda=np$。",
        sources=[{"document_id": references[0]["document_id"], "page": references[0]["page"]}],
    ), 250


generation.generate_one = mock_generate

# Explicitly mocked vision OCR; browser tests never transmit page images.
from backend import ocr  # noqa: E402

async def mock_ocr(image):
    await asyncio.sleep(.1)
    text = r"扫描页识别测试：若事件 A 与 B 相互独立，则 $P(A\cap B)=P(A)P(B)$。设 $P(A)=0.4$，$P(B)=0.5$，故 $P(A\cap B)=0.2$。"
    return ocr.decode_response({
        "choices": [{"finish_reason": "stop", "message": {"content": ocr.TEXT_START + "\n" + text + "\n" + ocr.TEXT_END}}],
        "usage": {"total_tokens": 180},
    })

ocr.recognize_page = mock_ocr


# Explicit test-only connection check; never use the real account from E2E.
from backend import deepseek  # noqa: E402

async def mock_connection(model):
    return {"connected": True, "ocr_model_available": True,
            "message": "DeepSeek 连接正常（HTTP 200），已确认可用 OCR 模型 deepseek-flash。（测试模拟响应）"}

deepseek.check_connection = mock_connection


# Blueprint extraction is deterministic here; production uses source-grounded API extraction.
from backend import planning, db
import json
real_run_plan = planning.run_plan
async def mock_plan(plan_id):
    row = db.one("SELECT * FROM exam_plans WHERE id=?", (plan_id,))
    if json.loads(row['config']).get('reading_mode') == 'vision':
        return await real_run_plan(plan_id)
    refs = json.loads(row['materials'])
    ref = refs[0]
    topics = [{'id': 'topic1', 'title': '事件独立性', 'objective': '根据独立性计算概率', 'weight': 1, 'reference_types': {'choice':3,'calculation':1} if json.loads(row['config']).get('mode')=='reference' else {}, 'reasons': ['测试主题'],
               'sources': [{'document_id': ref['document_id'], 'page': ref['page'], 'name': ref['name'], 'quote': ref['text'][:60]}]}]
    slots = planning.allocate(json.loads(row['config']), topics)
    db.execute("UPDATE exam_plans SET status='ready',topics=?,blueprint=?,tokens=50 WHERE id=?", (db.dump(topics),db.dump(slots),plan_id))
planning.run_plan = mock_plan
