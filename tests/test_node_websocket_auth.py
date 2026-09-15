"""节点的 WebSocket 面也在身份认证之内。

## 这条为什么必须单独存在

装上 `install_node_auth` 之后,HTTP 面确实 401 了。但 `@app.middleware("http")`
落到 Starlette 的 `BaseHTTPMiddleware`,它**只处理 `scope["type"] == "http"`**;
WebSocket 握手的 scope 是 `"websocket"`,整条不经过它。

所以"125 个节点的 HTTP 面都接上了认证"这句话是真的,而"这些节点都护住了"是假的 ——
实测(真 uvicorn、真握手):同一个 app 上 `GET /status` 401,而
`@app.websocket("/signaling/{device_id}")` 不带任何令牌照样连上并收到数据。
`nodes/Node_95_WebRTC_Receiver/main.py` 上就有这么一条。

`tests/test_node_http_auth.py` 那一组测试全绿,也照不出这个洞:它们一条都没连过 WS。

## 判据盯的是"连不上",不是"代码里有那个词"

底下每一条都真的发起握手。只断言 `node_auth.py` 里出现 `websocket` 字样是没用的 ——
模块 docstring 里就有这个词。
"""

import sys

import pytest

# 在**模块级**导入 —— 不是随手一写。
#
# 这个文件原本带 ``from __future__ import annotations``,并在 ``_app()`` 里局部
# ``import fastapi``。于是端点签名 ``websocket: fastapi.WebSocket`` 变成字符串
# 注解,FastAPI 用**模块**全局去解析,而 ``fastapi`` 只是 ``_app`` 的局部名 ——
# 解析不到,那个形参被当成普通请求参数,握手直接关闭。
#
# 它的现象是"带对令牌也连不上",和"鉴权层把正常调用方打断了"长得一模一样。
# 记在这里,是因为下一个照这个文件加用例的人会再踩一次。
fastapi = pytest.importorskip("fastapi")
FastAPI = fastapi.FastAPI
WebSocket = fastapi.WebSocket

TOKEN = "test-token-for-node-ws-auth"

ACCEPTED = []


def _app(monkeypatch):
    """一个最小节点:一条 HTTP、一条 WS,除 install_node_auth 外什么都没装。"""
    from nodes.common.node_auth import install_node_auth

    monkeypatch.setenv("GALAXY_API_TOKEN", TOKEN)
    monkeypatch.delenv("GALAXY_NODE_AUTH", raising=False)

    app = FastAPI()
    install_node_auth(app, "TestNode")

    @app.get("/status")
    def status():  # noqa: ANN202
        return {"ok": True}

    @app.websocket("/signaling/{device_id}")
    async def signaling(websocket: WebSocket, device_id: str):  # noqa: ANN202
        # 记在 accept **之前**:回绝必须发生在端点被调到之前,否则节点侧的
        # 连接表(Node_95 的 state.signaling_connections)已经被未认证方写过了。
        ACCEPTED.append(device_id)
        await websocket.accept()
        await websocket.send_text(f"hello-{device_id}")

    return app


@pytest.fixture
def client(monkeypatch):
    testclient = pytest.importorskip("fastapi.testclient")
    ACCEPTED.clear()
    return testclient.TestClient(_app(monkeypatch))


class TestWebSocketRequiresAuth:
    def test_a_handshake_without_a_token_is_refused(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/signaling/attacker"):
                pass
        assert exc.value.code == 1008

    def test_the_endpoint_never_runs_for_a_refused_handshake(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/signaling/attacker"):
                pass
        assert ACCEPTED == [], "回绝发生在 accept 之后:端点的副作用已经跑过了"

    def test_a_handshake_with_the_token_still_works(self, client):
        """差分的另一半:只验"没令牌连不上"的话,把整条路堵死也能通过。"""
        with client.websocket_connect("/signaling/dev-1", headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
            assert ws.receive_text() == "hello-dev-1"
        assert ACCEPTED == ["dev-1"]

    def test_a_wrong_token_is_refused(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/signaling/dev-1", headers={"Authorization": "Bearer not-the-token"}):
                pass
        assert ACCEPTED == []


class TestItFailsClosed:
    def test_it_refuses_when_the_auth_module_cannot_be_imported(self, monkeypatch):
        """拿不到 core.auth 时**不放行** —— 和 HTTP 面同一个方向。

        WS 面没有第二道闸:`nodes.common.action_gate` 是按动作名判定的,
        WS 端点没有动作名,一条都过不了它。所以这里失守就是全无遮拦。
        """
        testclient = pytest.importorskip("fastapi.testclient")
        from starlette.websockets import WebSocketDisconnect

        app = _app(monkeypatch)
        ACCEPTED.clear()
        monkeypatch.setitem(sys.modules, "core.auth", None)  # 触发 ImportError
        with testclient.TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/signaling/x", headers={"Authorization": f"Bearer {TOKEN}"}):
                    pass
        assert ACCEPTED == []


class TestTheOptOutSwitchStillApplies:
    def test_galaxy_node_auth_off_lets_a_websocket_through(self, monkeypatch):
        """开关是**一个**开关 —— HTTP 关了而 WS 还锁着,会让运维以为自己关掉了。"""
        testclient = pytest.importorskip("fastapi.testclient")
        app = _app(monkeypatch)
        ACCEPTED.clear()
        monkeypatch.setenv("GALAXY_NODE_AUTH", "off")
        with testclient.TestClient(app) as client:
            assert client.get("/status").status_code == 200
            with client.websocket_connect("/signaling/dev-2") as ws:
                assert ws.receive_text() == "hello-dev-2"


class TestEveryNodeWebSocketRouteIsCovered:
    """新加一条 @app.websocket 而忘了装认证,应当在这里红,而不是上线后。"""

    def test_nodes_with_a_websocket_route_install_node_auth(self):
        import ast
        import glob

        offenders = []
        for path in sorted(glob.glob("nodes/Node_*/main.py")):
            src = open(path, encoding="utf-8").read()
            if "websocket" not in src:
                continue
            tree = ast.parse(src)
            has_ws_route = any(
                isinstance(node, ast.Attribute)
                and node.attr == "websocket"
                and isinstance(node.value, ast.Name)
                and node.value.id == "app"
                for node in ast.walk(tree)
            )
            if not has_ws_route:
                continue
            installs = any(
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None)) == "install_node_auth"
                for node in ast.walk(tree)
            )
            if not installs:
                offenders.append(path)
        assert offenders == [], f"这些节点有 WebSocket 端点却没装认证: {offenders}"

    def test_the_scan_actually_finds_the_known_websocket_node(self):
        """扫描本身得会命中 —— 否则上一条会因为"一个都没扫到"而空转通过。"""
        src = open("nodes/Node_95_WebRTC_Receiver/main.py", encoding="utf-8").read()
        assert "@app.websocket" in src
