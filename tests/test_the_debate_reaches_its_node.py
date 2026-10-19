"""``POST /api/v1/agents/debate`` 真能打到 Node_126_AgentSwarm，而且节点认得它发过去的东西。

全面排查第 7 轮把 199 条写接口都打了一遍，这一条回 500 ——「服务 'agent_swarm' 端口未配置」。往下查，它从没通过过：

- 端口按「服务」查 ``agent_swarm``，而端口表里只有节点 ``Node_126_AgentSwarm``：一查就抛；
- 就算连上：发 ``question`` / ``rounds``，节点认 ``problem`` / ``max_rounds``；策略发缩写 ``COT``，节点认 ``chain_of_thought``；
- 不带身份（节点的 HTTP 面有鉴权）；节点是 lazy 档，没人把它拉起来；
- 节点那头每一步推理再去调 Node_58 的 ``/chat``，也不带身份（见 ``tests/test_all_node_http_surfaces_require_auth.py``）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
NODE = "Node_126_AgentSwarm"


def _node_request_model():
    """节点自己的 ``DebateRequest`` —— 发过去的东西用它来验，而不是在这里再抄一遍字段名。"""
    spec = importlib.util.spec_from_file_location("_node_126_main", REPO_ROOT / "nodes" / NODE / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DebateRequest


@pytest.fixture()
def api():
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def node(monkeypatch):
    """把发往节点的请求接到一个假的节点上；``state["up"]`` 为假时就像节点没起来（连不上）。"""
    state = {"up": True, "status": 200, "seen": [], "started": []}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if not state["up"]:
            raise httpx.ConnectError("connection refused", request=request)
        state["seen"].append(request)
        if state["status"] != 200:
            return httpx.Response(state["status"], text="boom")
        return httpx.Response(200, json={"final_solution": "42", "consensus_reached": True})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    async def ensure(name, trigger):
        state["started"].append(name)
        if state.get("can_start"):
            state["up"] = True
            return name
        return None

    import core.node_activation_policy as nap

    monkeypatch.setattr(nap, "ensure_node_started", ensure)
    return state


def test_it_posts_what_the_node_accepts_to_the_node(api, auth_headers, node):
    from core.port_config import get_node_url

    r = api.post(
        "/api/v1/agents/debate",
        json={"question": "1+1?", "strategies": ["COT", "tot"], "rounds": 2},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["final_solution"] == "42"
    (req,) = node["seen"]
    assert str(req.url) == f"{get_node_url(NODE)}/debate"
    sent = json.loads(req.content)
    parsed = _node_request_model()(**sent)  # 节点认不出就会在这里抛
    assert parsed.problem == "1+1?" and parsed.max_rounds == 2
    assert [s.value for s in parsed.strategies] == ["chain_of_thought", "tree_of_thought"]
    assert req.headers.get("authorization", "").startswith("Bearer "), "节点的 HTTP 面有鉴权，不带身份就是 401"


def test_an_unknown_strategy_is_the_caller_s_mistake(api, auth_headers, node):
    r = api.post("/api/v1/agents/debate", json={"question": "q", "strategies": ["VIBES"]}, headers=auth_headers)
    assert r.status_code == 422 and "VIBES" in r.text
    assert node["seen"] == []


def test_a_node_that_is_not_up_yet_is_started_on_first_use(api, auth_headers, node):
    node.update(up=False, can_start=True)
    r = api.post("/api/v1/agents/debate", json={"question": "q"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    # 辩手每一步都要调 Node_58 的 /chat：两个一起拉起来，先拉被依赖的那个
    assert node["started"] == ["Node_58_ModelRouter", NODE]


def test_a_node_that_cannot_be_started_is_a_503_that_says_so(api, auth_headers, node):
    node.update(up=False, can_start=False)
    r = api.post("/api/v1/agents/debate", json={"question": "q"}, headers=auth_headers)
    assert r.status_code == 503 and NODE in r.text


def test_the_node_failing_is_a_bad_gateway_not_this_endpoint_crashing(api, auth_headers, node):
    node["status"] = 500
    r = api.post("/api/v1/agents/debate", json={"question": "q"}, headers=auth_headers)
    assert r.status_code == 502
    assert r.json()["success"] is False and "HTTP 500" in r.json()["error"]
