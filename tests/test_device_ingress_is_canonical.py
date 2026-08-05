"""tests/test_device_ingress_is_canonical.py — 设备真的能连进来。

问题是什么
----------
仓库自己在 ``core/api_routes.py`` 的 ``CORE_COMPAT_DEVICE_INGRESS_POLICY_AUTHORITY``
里写得很清楚:

    core.api_routes 的兼容 WebSocket 接入**永远不等价于生产**。canonical 的
    Android/V2 设备接入是 galaxy_gateway.routes.websocket 的 /ws/device/{device_id}。

而 ``unified_launcher`` 此前**只**挂了那条兼容面。兼容面默认是禁用的
(要 ``GALAXY_ALLOW_PROTECTED_CORE_COMPAT_WS`` 才开),于是桌面本地部署上:

    capability_report → {"type": "compat_ws_disabled", ...}
    heartbeat         → {"type": "compat_ws_disabled", ...}

``capability_report`` 正是 Android/WearOS 在 ``onOpen`` 时发的**设备注册事件**
(见 ufo-galaxy-android 的 GalaxyApiClient 类注释)。也就是说设备根本连不进来,
而且不会报错 —— 服务端老老实实回了一个 JSON,客户端多半只是当成一条未知消息忽略。

这份测试钉什么
--------------
钉**行为**:握手之后发 ``capability_report``,必须拿到 ``capability_report_ack``,
而不是 ``compat_ws_disabled``。

不钉"某个函数被调用了" —— 那种断言在这件事上毫无价值:挂载写在 try/except 里,
"没抛错"不等于"挂上了";而且顺序错了也会静默失效(见下)。

顺序为什么要紧
--------------
FastAPI 对同一路径**先注册的赢**。canonical 必须排在兼容面前面。实测反过来放
(兼容面在前)修复完全不生效,返回的仍是 compat_ws_disabled —— 而路径存在性检查
一样是绿的。所以这里连"顺序"也一并钉住。
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")


def _build_launcher_style_app(canonical_first: bool = True):
    """按 unified_launcher 的方式组装 app。

    与启动器保持同一顺序是这份测试的全部意义所在 —— 换个顺序结论就变了,
    所以这里不"简化"成只挂 canonical。
    """
    os.environ.setdefault("GALAXY_NATS_ENABLED", "false")
    from fastapi import FastAPI

    from core.api_routes import create_api_routes, create_websocket_routes

    app = FastAPI()
    app.include_router(create_api_routes(service_manager=None, config=None))
    if canonical_first:
        from galaxy_gateway.routes.websocket import register_websocket_routes

        register_websocket_routes(app)
    create_websocket_routes(app, service_manager=None)
    if not canonical_first:
        from galaxy_gateway.routes.websocket import register_websocket_routes

        register_websocket_routes(app)
    return app


def _send(app, message: dict) -> dict:
    from fastapi.testclient import TestClient

    with TestClient(app).websocket_connect("/ws/device/probe-device") as ws:
        ws.send_json(message)
        return ws.receive_json()


CAPABILITY_REPORT = {
    "type": "capability_report",
    "device_id": "probe-device",
    "version": "3.0",
    "payload": {"capabilities": ["screen", "microphone"], "device_type": "android_phone"},
}
HEARTBEAT = {"type": "heartbeat", "device_id": "probe-device", "version": "3.0"}


class TestDevicesCanActuallyConnect:
    def test_capability_report_is_acked(self):
        """设备注册事件必须被真正处理。

        这一条红了就意味着手机/手表连上来之后**注册不了** —— 而且是静默的:
        服务端会回一个结构完整的 JSON,不是错误码。
        """
        resp = _send(_build_launcher_style_app(), CAPABILITY_REPORT)
        assert resp.get("type") == "capability_report_ack", (
            f"capability_report 没有被 canonical 接入处理,收到:{resp}。"
            "如果是 compat_ws_disabled,说明 canonical 没挂上或挂在了兼容面后面。"
        )

    def test_heartbeat_is_acked(self):
        resp = _send(_build_launcher_style_app(), HEARTBEAT)
        assert resp.get("type") == "heartbeat_ack", f"心跳没被处理:{resp}"

    def test_compat_disabled_response_never_reaches_devices(self):
        """``compat_ws_disabled`` 是这次修复要消灭的那个回包,不许再出现。"""
        for msg in (CAPABILITY_REPORT, HEARTBEAT):
            resp = _send(_build_launcher_style_app(), msg)
            assert resp.get("type") != "compat_ws_disabled", f"{msg['type']} 仍然撞在被禁用的兼容面上:{resp}"


class TestOrderMatters:
    def test_mounting_canonical_after_compat_does_not_work(self):
        """顺序放反时修复不生效 —— 把这个陷阱本身钉下来。

        FastAPI 对同一路径先注册的赢。这一条不是在测框架,是在防止有人日后
        "整理代码顺序"时把 canonical 挪到后面 —— 那会让设备重新连不进来,
        而任何"路径存在吗"的检查都照样绿。
        """
        resp = _send(_build_launcher_style_app(canonical_first=False), CAPABILITY_REPORT)
        assert resp.get("type") == "compat_ws_disabled", (
            "预期:兼容面先注册时会赢,于是收到 compat_ws_disabled。"
            f"实际收到 {resp} —— 若框架行为变了,本文件顶部关于顺序的说明需要重写。"
        )


class TestLauncherWiring:
    def test_launcher_registers_canonical_before_compat(self):
        """启动器源码里 canonical 的挂载必须排在兼容面之前。

        读源码而不是靠运行:启动器要跑起来得拉起一整套服务,在单测里不现实。
        但顺序是纯文本事实,可以直接查 —— 而它恰恰是最容易在重构中被打乱的东西。

        为什么按 AST 查而不是 ``src.find(字符串)``
        --------------------------------------------
        这一条原先找的是字面量 ``"create_websocket_routes(\\n                    self.app"``
        —— 把**调用怎么换行、缩进几格**编进了判据。启动器重做把这段代码从
        ``unified_launcher.py`` 搬进 ``launcher/services.py``,缩进层级变了,black 顺手
        把它收成一行,于是那个 find 返回 -1,断言炸在"启动器没有挂兼容 WebSocket 面"
        —— 而兼容面其实好好地挂着,顺序也仍然是对的。**报的是假警**。

        假警比漏报更坏一点:它没法靠改产品代码修好(代码本来就是对的),久了就会被
        当成噪音而被人加进忽略名单,那时它连真的顺序错乱也拦不住了。

        改成按 AST 找两个调用各自的行号 —— 换行、缩进、参数怎么排都不影响,而
        "谁先注册"这个真正要守的事实一字不差地守住。
        """
        import ast
        from pathlib import Path

        # 检查对象搬家了：UnifiedWebUI（挂路由的地方）已原样搬到
        # launcher/services.py；unified_launcher.py 只剩 CLI 外壳。
        src_path = Path(__file__).resolve().parent.parent / "launcher" / "services.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))

        def _first_call_line(func_name: str) -> int | None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
                    return node.lineno
            return None

        canonical_at = _first_call_line("register_websocket_routes")
        compat_at = _first_call_line("create_websocket_routes")
        assert canonical_at is not None, "启动器没有挂 canonical 设备接入"
        assert compat_at is not None, "启动器没有挂兼容 WebSocket 面(/ws/status 等会消失)"
        assert canonical_at < compat_at, (
            "canonical 设备接入被排到了兼容面后面 —— 同一路径先注册的赢,"
            f"这会让设备重新收到 compat_ws_disabled。(canonical 在第 {canonical_at} 行,"
            f"兼容面在第 {compat_at} 行)"
        )
