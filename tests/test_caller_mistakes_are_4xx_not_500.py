"""调用方传错了东西，回 4xx 说清楚错在哪 —— 不是 500「这边崩了」。

全面排查第 7 轮把 199 条写接口用空请求体、再用按 schema 填的请求体各打一遍，下面几条回 500：

- ``/api/v1/vision/understand`` 不带图：里面抛的 400 被外层 ``except Exception`` 接住改写成 500
  （detail 是「400: Image or video chunk required」）；
- ``/api/v1/vision/understand`` / ``/api/v1/vision/ocr`` 的图不是合法 base64：解码异常直接成了 500；
- ``/auth/oauth/device/poll`` 一个没配（或不支持）的提供商：``/device/start`` 先判了「配没配」回 400，
  ``/poll`` 没判，``ValueError`` 一路掉到最后回 500。

（MCP / 技能热重载一个没登记的名字回 404，见 ``tests/test_skill_reload_really_reloads.py``；辩论接口见
``tests/test_the_debate_reaches_its_node.py``。）
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api():
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "path, body, says",
    [
        ("/api/v1/vision/understand", {}, "Image or video chunk required"),
        ("/api/v1/vision/understand", {"image_base64": "r7"}, "base64"),
        ("/api/v1/vision/ocr", {"image_base64": "r7"}, "base64"),
        ("/auth/oauth/device/poll", {"provider": "r7", "device_code": "x"}, "not configured"),
    ],
)
def test_a_bad_request_is_a_400_that_says_why(api, auth_headers, path, body, says):
    r = api.post(path, json=body, headers=auth_headers)
    assert r.status_code == 400, f"{path} {body} → {r.status_code} {r.text}"
    assert says in r.json()["detail"]
