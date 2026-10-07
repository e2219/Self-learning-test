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
        stem=f"练习 {question['position']}：设事件 $A$ 与 $B$ 相互独立，且 $P(A)=0.4$，$P(B)=0.5$。求 $P(A\\cap B)$。",
        options=["$0.2$", "$0.4$", "$0.5$", "$0.9$"] if kind == "choice" else [],
        answer="A" if kind == "choice" else "正确" if kind == "true_false" else "$P(A\\cap B)=0.2$",
        explanation="由事件独立的定义，有：\n\n$$P(A\\cap B)=P(A)P(B)=0.4\\times0.5=0.2.$$\n\n注意独立与互斥的区别。此处两事件可以同时发生。",
        rubric=["正确写出独立事件的乘法公式。", "正确代入数值并计算。"],
        knowledge="事件独立性 · 概率乘法公式",
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
