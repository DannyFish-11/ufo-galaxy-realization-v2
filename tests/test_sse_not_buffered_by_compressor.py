"""回归测试:SSE 流式响应绝不能被压缩/缓存中间件读干缓冲。

背景:桌面对话"文字整段蹦出、不逐字流"的根因是 ResponseCompressor 命中
`text/event-stream`(因 "text/" 子串判断),把整条 SSE 流抽干成一个 buffer 再一次性
返回,于是逐 token 的 delta 帧被攒到生成结束才到达前端。本测试锁死"SSE 原样透传、
普通 JSON 仍正常压缩"这两条不变量,防止回归。
"""

import gzip

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.performance import ResponseCompressor, _is_streaming_response  # noqa: E402


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ResponseCompressor, min_size=1)  # min_size=1 → 连小 JSON 也会压

    @app.get("/sse")
    async def sse():
        async def gen():
            for i in range(5):
                yield f'data: {{"type":"delta","text":"tok{i}"}}\n\n'.encode()

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/json")
    async def json_route():
        return JSONResponse({"payload": "x" * 2000})

    return app


def test_sse_response_is_not_gzip_buffered():
    """SSE 路由:不应带 content-encoding: gzip,且能收到全部 5 个分帧。"""
    client = TestClient(_build_app())
    with client.stream("GET", "/sse", headers={"accept-encoding": "gzip"}) as r:
        assert r.status_code == 200
        assert "event-stream" in r.headers.get("content-type", "")
        # 关键:SSE 不能被 gzip(gzip 必然意味着被读干缓冲过)
        assert r.headers.get("content-encoding") != "gzip", "SSE 被压缩中间件缓冲了!"
        body = b"".join(r.iter_raw())
    # 全部 5 帧都在,且是可分帧的 SSE 文本(未被压成二进制)
    text = body.decode("utf-8")
    for i in range(5):
        assert f"tok{i}" in text
    assert text.count("data:") == 5


def test_plain_json_still_compresses():
    """普通 JSON 响应仍应被正常 gzip —— 不能因豁免 SSE 而误伤压缩。"""
    client = TestClient(_build_app())
    # httpx 会自动解压;用 raw 流看真实 content-encoding
    with client.stream("GET", "/json", headers={"accept-encoding": "gzip"}) as r:
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip", "普通 JSON 压缩被误伤!"
        raw = b"".join(r.iter_raw())
    # 原样是 gzip 字节,解压后是原 JSON
    decompressed = gzip.decompress(raw).decode("utf-8")
    assert "payload" in decompressed


def test_is_streaming_response_helper():
    """辅助判据:SSE content-type 命中,普通 JSON 不命中。"""

    class _R:
        def __init__(self, ctype):
            self.headers = {"content-type": ctype}

    assert _is_streaming_response(_R("text/event-stream")) is True
    assert _is_streaming_response(_R("text/event-stream; charset=utf-8")) is True
    assert _is_streaming_response(_R("application/json")) is False
    assert _is_streaming_response(_R("text/plain")) is False
