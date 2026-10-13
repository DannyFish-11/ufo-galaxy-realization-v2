"""视觉理解与 OCR 两个接口回的是结论,不是 500。

原先 ``/api/v1/vision/understand`` 把协程方法 ``VisionPipeline.understand`` 丢进线程池,拿回的是没 await 的
协程对象,序列化时炸成 500 —— 这个接口从来没成功过;``/api/v1/vision/ocr`` 调的 ``DeepSeekOCR2Adapter`` /
``process_image`` 都不存在,永远回「cannot import name」。
"""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

IMG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


@pytest.fixture()
def client():
    from core.routes import vision

    app = FastAPI()
    app.include_router(vision.create_router())
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_understand_awaits_the_pipeline_and_reports_its_result(client, monkeypatch):
    from core import vision_pipeline

    seen = {}

    async def fake_understand(self, image_base64=None, image_path=None, mode="full", task_context=""):
        seen.update(image_base64=image_base64, mode=mode, task_context=task_context)
        return vision_pipeline.VisionResult(success=True, raw_text="你好", engine_used="fake")

    monkeypatch.setattr(vision_pipeline.VisionPipeline, "understand", fake_understand)
    r = client.post(
        "/api/v1/vision/understand", json={"image_base64": IMG, "mode": "ocr_only", "instruction": "找按钮"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["engine"] == "fake" and body["result"]["full_text"] == "你好"
    assert seen == {"image_base64": IMG, "mode": "ocr_only", "task_context": "找按钮"}


def test_understand_without_any_engine_says_so(client, monkeypatch):
    from core import vision_pipeline

    async def nothing(self, **_):
        return vision_pipeline.VisionResult(success=False, error="所有视觉引擎都不可用")

    monkeypatch.setattr(vision_pipeline.VisionPipeline, "understand", nothing)
    r = client.post("/api/v1/vision/understand", json={"image_base64": IMG})
    assert r.status_code == 200 and r.json()["success"] is False
    assert r.json()["error"] == "所有视觉引擎都不可用"


def test_ocr_without_a_key_says_what_to_configure(client, monkeypatch):
    for k in ("NOVITA_API_KEY", "DEEPSEEK_OCR_API_KEY", "DEEPSEEK_OCR2_LOCAL_URL"):
        monkeypatch.delenv(k, raising=False)
    body = client.post("/api/v1/vision/ocr", json={"image_base64": IMG}).json()
    assert body["success"] is False and "NOVITA_API_KEY" in body["error"], body
    assert "cannot import" not in body["error"]


def test_ocr_calls_the_adapter_method_for_the_mode(client, monkeypatch):
    from nodes.Node_15_OCR.core import deepseek_ocr_adapter as mod

    monkeypatch.setenv("DEEPSEEK_OCR2_LOCAL_URL", "http://127.0.0.1:9")
    called = {}

    async def tables(self, image_source):
        called["b64"] = image_source
        return {"success": True, "text": "| a | b |"}

    monkeypatch.setattr(mod.DeepSeekOCRAdapter, "extract_tables", tables)
    body = client.post("/api/v1/vision/ocr", json={"image_base64": IMG, "mode": "tables"}).json()
    assert body == {"success": True, "engine": "deepseek_ocr2", "text": "| a | b |", "blocks": [], "confidence": 0.0}
    assert base64.b64decode(called["b64"]) == base64.b64decode(IMG)
