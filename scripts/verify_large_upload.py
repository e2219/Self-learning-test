"""Exercise a 512 MB upload over real HTTP without touching personal data.

Run with .venv/bin/python scripts/verify_large_upload.py after installing the
development requirements. The PDF is synthetically padded, not a textbook.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_api import sample_pdf  # noqa: E402


def main():
    size = 512 * 1024 * 1024
    code = "large-upload-test-only"
    with tempfile.TemporaryDirectory(prefix="zhixi-large-upload-") as folder:
        root = Path(folder)
        original = sample_pdf()
        split = original.rindex(b"startxref")
        source = root / "synthetic-512mb.pdf"
        with source.open("wb") as output:
            output.write(original[:split] + b"%")
            output.seek(size - len(original) - 2, 1)
            output.write(b"\n" + original[split:])
        assert source.stat().st_size == size
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "STUDY_DATA_DIR": str(root / "data"),
               "STUDY_ACCESS_CODE": code, "DEEPSEEK_API_KEY": "",
               "STUDY_MAX_PDF_MB": "1024", "STUDY_MAX_PDF_PAGES": "2000"}
        with (root / "server.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
                 "--port", str(port), "--log-level", "warning"],
                cwd=ROOT, env=env, stdout=log, stderr=log,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                                  timeout=httpx.Timeout(180, connect=5)) as client:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            client.get("/api/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            if time.monotonic() > deadline or process.poll() is not None:
                                raise RuntimeError((root / "server.log").read_text())
                            time.sleep(.1)
                    client.post("/api/login", json={"code": code}).raise_for_status()
                    response = client.post("/api/courses", json={"name": "大文件上传验收"})
                    response.raise_for_status()
                    course = response.json()
                    started = time.monotonic()
                    with source.open("rb") as stream:
                        response = client.post(f"/api/courses/{course['id']}/documents",
                                               files={"file": (source.name, stream, "application/pdf")})
                    response.raise_for_status()
                    document = response.json()
                    assert document["page_count"] == 1
                    saved = root / "data/uploads" / f"{document['id']}.pdf"
                    assert saved.stat().st_size == size
                    page = client.get(f"/api/documents/{document['id']}/pages/1")
                    page.raise_for_status()
                    assert "Probability" in page.json()["text"]
                    result = {"result": "passed", "size_mb": 512, "page_count": 1,
                              "seconds": round(time.monotonic() - started, 2)}
                    status = Path(f"/proc/{process.pid}/status")
                    if status.exists():
                        for line in status.read_text().splitlines():
                            if line.startswith("VmHWM:"):
                                result["server_peak_rss_mb"] = round(int(line.split()[1]) / 1024, 2)
                    print(json.dumps(result, ensure_ascii=False))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
