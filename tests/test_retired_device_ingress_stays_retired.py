"""旧的设备 WebSocket 入口退役了,也一直退着(2026-11-02,所有者:「退役吧,确保没有东西在用它也不影响什么」)。

退役的三条:``/ws/android/{device_id}``、``/ws/android``、``/ws/ufo3/{device_id}``。退役前核对过:

* 安卓 App(``DannyFish-11/ufo-galaxy-android``,完整 195 个提交)与手表(``DannyFish-11/galaxy-wearos``,完整 141 个提交)
  的源码历史里一次都没连过这三条 —— 两边一直只连 ``/ws/device/{device_id}``;
* 安卓 App 读客户端配置发现时期望 ``ws_paths`` 是对象,而服务端给的是列表,于是一直落回它内置的 ``/ws/device/{device_id}``
  —— 那份列表里的旧路径从没被任何客户端用上;
* 本仓库里没有任何客户端、部署配置、启动脚本在用这三条。

退役 = 这三条没有路由(握手时就被拒,不进处理器)、入口登记表与配置发现里不再出现、用量账里不再登记、
``/ws/ufo3`` 那把只为它存在的开关(``GALAXY_ENABLE_LEGACY_PROTOCOLS``)随之删除。规范入口照旧。
"""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

REPO = pathlib.Path(__file__).resolve().parent.parent
RETIRED = ("/ws/android/{device_id}", "/ws/android", "/ws/ufo3/{device_id}")


@pytest.fixture()
def client():
    from galaxy_gateway.routes.websocket import register_websocket_routes

    app = FastAPI()
    register_websocket_routes(
        app
    )  # 独立网关(galaxy_gateway/app.py)与桌面版(launcher/services.py)都只经这一处挂设备入口
    return TestClient(app)


@pytest.mark.parametrize("path", ["/ws/android/{id}", "/ws/android?device_id={id}", "/ws/ufo3/{id}"])
def test_a_client_on_a_retired_path_is_refused_at_the_handshake(client, path):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path.format(id=f"old-{uuid.uuid4().hex[:6]}")):
            pass


def test_the_one_device_ingress_still_works(client):
    did = f"dev-{uuid.uuid4().hex[:6]}"
    with client.websocket_connect(f"/ws/device/{did}") as ws:
        ws.send_json({"type": "heartbeat", "device_id": did, "version": "3.0"})
        assert isinstance(ws.receive_json(), dict), "规范入口照旧收发"


def test_the_ingress_registry_lists_only_what_is_mounted(client):
    from galaxy_gateway.routes.websocket import DEVICE_WS_INGRESS_SURFACE_REGISTRY

    listed = {e["path"]: e["classification"] for e in DEVICE_WS_INGRESS_SURFACE_REGISTRY}
    assert listed == {"/ws/device/{device_id}": "canonical", "/ws/webrtc/{device_id}": "media"}
    mounted = {getattr(r, "path", "") for r in client.app.routes if "WebSocket" in type(r).__name__}
    assert mounted == set(listed), "登记表说的就是真挂着的那几条"


def test_config_discovery_hands_out_only_the_device_path():
    from galaxy_gateway.api.config import _WS_COMPAT_PATHS, _WS_PATHS

    assert _WS_PATHS == ["/ws/device/{id}"]
    assert _WS_COMPAT_PATHS == [], "键留着、给空表:按旧字段解析的客户端不会因为少一个键出错"


def test_the_usage_ledger_no_longer_tracks_them():
    from core.compat_usage import COMPAT_SURFACES

    assert not [s for s in COMPAT_SURFACES if s.startswith("/ws/")]


def test_nothing_in_the_repo_mounts_or_dials_a_retired_path():
    """代码里(测试与文档以外)不再有人挂、也不再有人连这三条;只为 /ws/ufo3 存在的开关也没人读了。"""
    hits = []
    # 挂路由、拼 URL 都是字符串字面量里的路径("/ws/android…" / '/ws/ufo3…' / f"…/ws/android…");文档串里的说明不算
    pattern = re.compile(r"""["'][^"'\n]*/ws/(android|ufo3)\b""")
    for path in REPO.rglob("*"):
        rel = path.relative_to(REPO).as_posix()
        if not path.is_file() or path.suffix not in {
            ".py",
            ".js",
            ".ts",
            ".kt",
            ".json",
            ".yml",
            ".yaml",
            ".sh",
            ".ps1",
            ".conf",
        }:
            continue
        if rel.startswith(("tests/", ".git/", "external/", "audit/")) or "node_modules" in rel or "/dist/" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:120]}")
            if "GALAXY_ENABLE_LEGACY_PROTOCOLS" in line and "随之删除" not in line:
                hits.append(f"{rel}:{n}: {line.strip()[:120]}")
    assert hits == [], "\n".join(hits)
