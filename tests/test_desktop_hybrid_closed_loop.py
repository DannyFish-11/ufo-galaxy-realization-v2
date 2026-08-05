#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_desktop_hybrid_closed_loop.py
============================================
桌面混合闭环：结构化降级链与视觉闭环必须是**同一条路**，且不得互相递归。

仓库里本来有两条互不知道对方的路：

* ``WindowsExecutionArbiter``：System API → UIA → GUI → VLM 四级降级。
  ``windows_aip_client`` 声称它是自己**唯一**的执行入口。
* ``ComputerUseLoop``：感知 → 规划 → 安全门 → 执行 → 再感知 的完整视觉闭环，
  只挂在 REST 路由 / openclawd 工具上。

三处真实断链：

D1. **第 3 级(GUI)默认适配器调的是幽灵方法。**
    它调 ``device_control.execute_action(...)``，而这个方法在本仓库**从未存在过**
    （``git log -S "def execute_action"`` 为空）。于是四级里唯一被自动接上的那一级
    每次都以 ``AttributeError: 'DeviceControlService' object has no attribute
    'execute_action'`` 失败。

D2. **第 4 级(VLM)是四级中唯一没有默认适配器的那一级。**
    前三级都有 ``_make_default_*_executor()``，第 4 级没有，执行到这里只会返回
    "No VLM executor configured" —— 结构化三级失败就等于整个执行失败，而仓库里
    明明有一套能干这事的闭环。

D3. **``ComputerUseLoop`` 的每一步动作直奔坐标级派发。**
    ``invoke_node(Node_36)`` 跳过了整条结构化降级链：「打开记事本」本来一个 Win32
    调用就够，却被规划成点坐标，又慢又脆。

接通两侧就产生**无限递归**：结构级全失败 → VLM 级 → 闭环 → 动作 → 仲裁器 → …。
不变式：**computer-use 闭环运行期间，仲裁器不得再降级到第 4 级**。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from core.computer_use_loop import ComputerUseLoop
from core.device_control_service import DeviceControlService
from core.windows_execution_arbiter import (
    WindowsExecutionArbiter,
    WinExecLevel,
    computer_use_recursion_guard_active,
)


class _RecordingDeviceControl(DeviceControlService):
    """记录真正被调到哪个方法 —— 判据是「落到真方法上」，不是「没抛异常」。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls: List[str] = []

    async def click(self, device_id, x, y, clicks=1):  # type: ignore[override]
        self.calls.append(f"click:{x},{y},{clicks}")
        return {"success": True}

    async def input_text(self, device_id, text):  # type: ignore[override]
        self.calls.append(f"input_text:{text}")
        return {"success": True}

    async def scroll(self, device_id, direction="down", amount=500):  # type: ignore[override]
        self.calls.append(f"scroll:{direction},{amount}")
        return {"success": True}

    async def press_key(self, device_id, key):  # type: ignore[override]
        self.calls.append(f"press_key:{key}")
        return {"success": True}

    async def open_app(self, device_id, app_name):  # type: ignore[override]
        self.calls.append(f"open_app:{app_name}")
        return {"success": True}

    async def screenshot(self, device_id):  # type: ignore[override]
        self.calls.append("screenshot")
        return {"success": True}


# ===========================================================================
# D1、GUI 级默认适配器必须调到真方法
# ===========================================================================


def test_gui_level_no_longer_calls_a_phantom_method(monkeypatch) -> None:
    """跑一次真的 click：GUI 级不得再以 AttributeError 收场。"""
    rec = _RecordingDeviceControl()
    monkeypatch.setattr("core.device_control_service.device_control", rec)

    async def _run():
        arb = WindowsExecutionArbiter(system_api_executor=None, uia_executor=None)
        return await arb.execute(action="click", params={"x": 7, "y": 9}, device_id="local")

    result = asyncio.run(_run())
    gui = [a for a in result.attempts if a["level"] == "gui"]
    assert gui, "GUI 级根本没被尝试"
    assert "has no attribute" not in (gui[0].get("error") or ""), "GUI 级仍在调一个不存在的方法"
    assert rec.calls == ["click:7,9,1"], f"动作没有落到真正的控制方法上: {rec.calls}"


@pytest.mark.parametrize(
    "action,params,expected",
    [
        ("click", {"x": 1, "y": 2}, "click:1,2,1"),
        ("double_click", {"x": 3, "y": 4}, "click:3,4,2"),
        ("type", {"text": "hi"}, "input_text:hi"),
        ("input", {"text": "hi"}, "input_text:hi"),
        ("scroll", {"direction": "up", "amount": 120}, "scroll:up,120"),
        ("press_key", {"key": "enter"}, "press_key:enter"),
        ("open_app", {"app_name": "notepad"}, "open_app:notepad"),
        ("screenshot", {}, "screenshot"),
    ],
)
def test_execute_action_dispatches_every_supported_action(action, params, expected) -> None:
    """每个受支持的动作都必须落到对应的真方法上。"""
    rec = _RecordingDeviceControl()
    out = asyncio.run(rec.execute_action("dev", action, params))
    assert out.get("success") is True
    assert rec.calls == [expected], f"{action} 派发错了: {rec.calls}"


def test_press_key_now_has_a_dispatch_path() -> None:
    """``press_key`` 早就实现了，旧分发表里却没有它 —— 实现了却按不到键。"""
    rec = _RecordingDeviceControl()
    asyncio.run(rec.execute_action("dev", "press_key", {"key": "f5"}))
    assert rec.calls == ["press_key:f5"], "press_key 仍然没有任何派发路径"


def test_unsupported_action_is_reported_not_faked() -> None:
    """不支持的动作必须如实报，谎报成功会让仲裁器的降级链在这里断掉。"""
    rec = _RecordingDeviceControl()
    out = asyncio.run(rec.execute_action("dev", "right_click", {"x": 1, "y": 2}))
    assert out.get("success") is False, "不支持的动作被谎报成功 —— 降级链不会再往下走"
    assert out.get("unsupported") is True
    assert not rec.calls, "不支持的动作却调了某个方法"


def test_cross_device_control_uses_the_same_dispatch_table() -> None:
    """跨设备控制不得再维护第二张分发表（两张表就是改一处漏一处）。"""
    rec = _RecordingDeviceControl()
    seen: Dict[str, Any] = {}

    async def _spy(device_id, action, params):
        seen["args"] = (device_id, action, params)
        return {"success": True}

    rec.execute_action = _spy  # type: ignore[assignment]
    asyncio.run(rec.register_device("target", "windows", "Target"))
    asyncio.run(rec.control_device("src", "target", "click", {"x": 5, "y": 6}))
    assert seen.get("args") == ("target", "click", {"x": 5, "y": 6}), "control_device 仍在自己分发"


# ===========================================================================
# D2、VLM 级必须像其它三级一样有默认适配器
# ===========================================================================


def test_vlm_level_is_no_longer_an_empty_socket(monkeypatch) -> None:
    """结构级全失败后，第 4 级不得再回 "No VLM executor configured"。"""
    seen: Dict[str, Any] = {}

    async def _fake_task(instruction, **kw):
        seen["instruction"] = instruction
        return {"success": True, "stop_reason": "done", "message": "ok", "steps": []}

    monkeypatch.setattr("core.computer_use_loop.run_computer_use_task", _fake_task)

    async def _run():
        arb = WindowsExecutionArbiter(use_defaults=False)
        arb._vlm = __import__(
            "core.windows_execution_arbiter", fromlist=["_make_default_vlm_executor"]
        )._make_default_vlm_executor()
        return await arb.execute(action="click", params={}, device_id="local", instruction="点确定")

    result = asyncio.run(_run())
    assert result.success is True, "第 4 级没有真的把活干了"
    assert result.final_level is WinExecLevel.VLM
    assert seen.get("instruction") == "点确定", "指令没有透传给视觉闭环"


def test_production_arbiter_wires_the_vlm_level_like_the_others() -> None:
    """生产同款构造（use_defaults=True）下，四级都不得是空插座。"""
    arb = WindowsExecutionArbiter()
    assert arb._vlm is not None, "第 4 级仍是四级里唯一没有默认适配器的那一级"


def test_vlm_level_reports_honestly_when_computer_use_is_disabled(monkeypatch) -> None:
    """闭环被关掉时如实报原因，不得谎称动作做过了。"""
    monkeypatch.setenv("GALAXY_COMPUTER_USE", "0")

    async def _run():
        arb = WindowsExecutionArbiter(use_defaults=False)
        arb._vlm = __import__(
            "core.windows_execution_arbiter", fromlist=["_make_default_vlm_executor"]
        )._make_default_vlm_executor()
        return await arb.execute(action="click", params={}, device_id="local", instruction="点确定")

    result = asyncio.run(_run())
    assert result.success is False
    vlm = [a for a in result.attempts if a["level"] == "vlm"][0]
    assert "GALAXY_COMPUTER_USE" in (vlm.get("error") or ""), "关掉的原因没有如实报出来"


# ===========================================================================
# D3 + 递归保护
# ===========================================================================


def test_computer_use_actions_go_through_the_arbiter(monkeypatch) -> None:
    """闭环的一步动作必须先经仲裁器的结构化降级链，而不是直奔坐标派发。"""
    hits: List[str] = []

    class _Arb:
        async def execute(self, *, action, params, device_id, instruction):
            hits.append(action)

            class _R:
                success = True
                final_level = WinExecLevel.SYSTEM_API

            return _R()

    monkeypatch.setattr("core.windows_execution_arbiter.get_windows_arbiter", lambda: _Arb())

    from core.computer_use_loop import _default_act

    out = asyncio.run(_default_act("click", {"x": 1, "y": 2}, "Node_36_UIAWindows"))
    assert hits == ["click"], "动作绕开了仲裁器 —— 结构化降级链等于不存在"
    assert out["success"] is True


def test_computer_use_falls_back_to_node_dispatch_when_arbiter_cannot_act(monkeypatch) -> None:
    """仲裁器结构级都不行时，既有节点派发必须仍然生效 —— 今天能跑的不得跑不了。"""
    dispatched: List[str] = []

    class _Arb:
        async def execute(self, **kw):
            class _R:
                success = False
                final_level = WinExecLevel.GUI

            return _R()

    async def _fake_invoke(node_id, action, params, **kw):
        dispatched.append(f"{node_id}:{action}")

        class _R:
            success = True
            error = ""

        return _R()

    monkeypatch.setattr("core.windows_execution_arbiter.get_windows_arbiter", lambda: _Arb())
    monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)

    from core.computer_use_loop import _default_act

    out = asyncio.run(_default_act("click", {"x": 1, "y": 2}, "Node_36_UIAWindows"))
    assert dispatched == ["Node_36_UIAWindows:click"], "仲裁器失败后没有回落既有派发路径"
    assert out["success"] is True


def test_arbiter_does_not_recurse_into_vlm_while_the_loop_runs(monkeypatch) -> None:
    """核心不变式：闭环跑动期间，它发出的动作不得再把仲裁器降级到 VLM 级。

    不设防的话：结构级全失败 → VLM → 闭环 → 动作 → 仲裁器 → …… 无限递归。
    判据是闭环**只被进入一次**。
    """
    entries: List[str] = []

    async def _perceive():
        return "ZmFrZS1zY3JlZW4="  # 一帧假屏幕，足以进入规划

    async def _plan(self, instruction, history, screen_b64):
        # 第一步就发一个动作；动作会打回仲裁器
        return {"action": "click", "reason": "test", "x": 1, "y": 2}

    real_arb = WindowsExecutionArbiter(use_defaults=False)
    real_arb._vlm = __import__(
        "core.windows_execution_arbiter", fromlist=["_make_default_vlm_executor"]
    )._make_default_vlm_executor()

    monkeypatch.setattr("core.windows_execution_arbiter.get_windows_arbiter", lambda: real_arb)
    monkeypatch.setattr(ComputerUseLoop, "_plan_step", _plan)

    async def _counting_task(instruction, **kw):
        entries.append(instruction)
        loop = ComputerUseLoop(perceive_fn=_perceive)
        return await loop.run(instruction, max_steps=1)

    monkeypatch.setattr("core.computer_use_loop.run_computer_use_task", _counting_task)

    async def _fake_invoke(node_id, action, params, **kw):
        class _R:
            success = False
            error = "node unavailable"

        return _R()

    monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)

    result = asyncio.run(
        real_arb.execute(action="click", params={"x": 1, "y": 2}, device_id="local", instruction="点确定")
    )
    assert len(entries) == 1, f"视觉闭环被递归进入了 {len(entries)} 次 —— 递归保护没生效"
    assert result.result.get("vlm_level_excluded") is None, "最外层那次调用不该被递归保护挡掉"


def test_recursion_guard_reports_why_the_level_was_dropped(monkeypatch) -> None:
    """少一级要说清是被谁挡掉的，不得安静砍掉。"""
    from core.windows_execution_arbiter import _in_computer_use_loop

    async def _run():
        token = _in_computer_use_loop.set(True)
        try:
            arb = WindowsExecutionArbiter(use_defaults=False)
            return await arb.execute(action="click", params={}, device_id="local", instruction="x")
        finally:
            _in_computer_use_loop.reset(token)

    result = asyncio.run(_run())
    assert result.result.get("vlm_level_excluded") == "computer_use_loop_in_progress"
    assert not [a for a in result.attempts if a["level"] == "vlm"], "递归保护下仍然尝试了 VLM 级"


def test_recursion_guard_is_released_after_the_loop_finishes(monkeypatch) -> None:
    """跑完必须复位，否则一次调用之后 VLM 级就永久瞎了。"""

    async def _perceive():
        return None  # 立刻以 no_perception 收场，够验证复位

    async def _run():
        assert computer_use_recursion_guard_active() is False, "起点就不该置位"
        loop = ComputerUseLoop(perceive_fn=_perceive)
        await loop.run("随便什么任务", max_steps=1)
        return computer_use_recursion_guard_active()

    assert asyncio.run(_run()) is False, "闭环结束后递归保护没有复位 —— VLM 级从此再也不会被尝试"


def test_guard_is_set_while_the_loop_is_running() -> None:
    """对照组：跑动期间必须**确实**置位，否则上一条是空断言。"""
    seen: Dict[str, Any] = {}

    async def _perceive():
        seen["during"] = computer_use_recursion_guard_active()
        return None

    async def _run():
        loop = ComputerUseLoop(perceive_fn=_perceive)
        await loop.run("随便什么任务", max_steps=1)

    asyncio.run(_run())
    assert seen.get("during") is True, "闭环跑动期间根本没有置位 —— 递归保护形同虚设"
