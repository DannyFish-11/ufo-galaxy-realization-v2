"""tests/test_computer_use_loop.py
====================================
computer use 自主闭环:感知→规划→安全门→执行→再感知。

验证:完整闭环按序执行并在 done 停止;感知缺失如实拒跑(绝不闭眼操作);
白名单拒绝幻觉动作;死循环检测;步数上限;dry_run 不落真动作;总开关;
规划 JSON 解析容错。全部依赖注入,不触网、不动真键鼠。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from core.computer_use_loop import (
    ALLOWED_ACTIONS,
    ComputerUseLoop,
    _parse_action_json,
    computer_use_enabled,
)


@dataclass
class _FakeResp:
    content: str


@dataclass
class _ScriptedRouter:
    """按脚本依次吐动作 JSON 的假规划模型。"""

    script: List[Dict[str, Any]] = field(default_factory=list)
    calls: List[Any] = field(default_factory=list)
    _i: int = 0

    async def chat(self, messages=None, **kw):
        self.calls.append(messages)
        step = self.script[min(self._i, len(self.script) - 1)]
        self._i += 1
        return _FakeResp(content=json.dumps(step, ensure_ascii=False))


def _loop(script, *, screen: str = "FAKE_B64", acts=None, fail_act=False):
    dispatched: List[Dict] = acts if acts is not None else []

    async def _perceive():
        return screen

    async def _act(action, params, node_id):
        dispatched.append({"action": action, "params": params, "node_id": node_id})
        return {"success": not fail_act, "error": "act failed" if fail_act else ""}

    return ComputerUseLoop(router=_ScriptedRouter(script=script), perceive_fn=_perceive, act_fn=_act), dispatched


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("GALAXY_CU_SETTLE_S", "0")
    monkeypatch.delenv("GALAXY_COMPUTER_USE", raising=False)
    monkeypatch.delenv("GALAXY_CU_MAX_STEPS", raising=False)


# ───────────────────── 完整闭环 ─────────────────────


def test_full_loop_click_type_done():
    loop, dispatched = _loop(
        [
            {"action": "click", "x": 100, "y": 200, "reason": "点输入框"},
            {"action": "type", "text": "你好", "reason": "输入内容"},
            {"action": "done", "result": "已输入完成", "reason": "任务完成"},
        ]
    )
    out = asyncio.run(loop.run("在输入框输入你好"))
    assert out["success"] is True and out["stop_reason"] == "done"
    assert out["message"] == "已输入完成"
    assert [d["action"] for d in dispatched] == ["click", "type"]
    assert dispatched[0]["params"] == {"x": 100, "y": 200}
    assert len(out["steps"]) == 3


def test_planner_sees_history_and_screenshot():
    router = _ScriptedRouter(
        script=[
            {"action": "click", "x": 1, "y": 2, "reason": "r1"},
            {"action": "done", "result": "ok"},
        ]
    )

    async def _perceive():
        return "SCREEN_B64"

    async def _act(action, params, node_id):
        return {"success": True, "error": ""}

    loop = ComputerUseLoop(router=router, perceive_fn=_perceive, act_fn=_act)
    asyncio.run(loop.run("任务"))
    # 第二次规划调用必须带第一步的历史 + 截图(闭环的"再感知"证据)
    second = router.calls[1]
    user = next(m for m in second if m["role"] == "user")
    text_part = next(p["text"] for p in user["content"] if p["type"] == "text")
    assert "步骤1: click" in text_part
    img_part = next(p for p in user["content"] if p["type"] == "image_url")
    assert "SCREEN_B64" in img_part["image_url"]["url"]


# ───────────────────── 安全边界 ─────────────────────


def test_no_perception_refuses_to_act():
    loop, dispatched = _loop([{"action": "click", "x": 1, "y": 1}], screen=None)
    out = asyncio.run(loop.run("任务"))
    assert out["stop_reason"] == "no_perception" and not dispatched  # 绝不闭眼操作


def test_hallucinated_action_rejected():
    loop, dispatched = _loop([{"action": "format_disk", "reason": "?"}])
    out = asyncio.run(loop.run("任务"))
    assert out["stop_reason"] == "action_rejected" and not dispatched


def test_loop_detection_stops_repetition():
    loop, dispatched = _loop([{"action": "click", "x": 5, "y": 5, "reason": "同一处"}] * 10)
    out = asyncio.run(loop.run("任务"))
    assert out["stop_reason"] == "loop_detected"
    assert len(dispatched) == 2  # 第 3 次重复在执行前被拦下


def test_max_steps_cap():
    script = [{"action": "click", "x": i, "y": i} for i in range(100)]
    loop, dispatched = _loop(script)
    out = asyncio.run(loop.run("任务", max_steps=4))
    assert out["stop_reason"] == "max_steps" and len(dispatched) == 4


def test_dry_run_plans_but_never_dispatches():
    loop, dispatched = _loop([{"action": "click", "x": 9, "y": 9, "reason": "预览"}])
    out = asyncio.run(loop.run("任务", dry_run=True))
    assert out["success"] is True and out["stop_reason"] == "dry_run" and not dispatched


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("GALAXY_COMPUTER_USE", "0")
    assert computer_use_enabled() is False
    loop, dispatched = _loop([{"action": "done", "result": "x"}])
    out = asyncio.run(loop.run("任务"))
    assert out["stop_reason"] == "disabled" and not dispatched


def test_model_declares_fail_honestly():
    loop, _ = _loop([{"action": "fail", "result": "目标窗口不存在", "reason": "找不到"}])
    out = asyncio.run(loop.run("任务"))
    assert out["success"] is False and out["stop_reason"] == "fail"
    assert "目标窗口不存在" in out["message"]


def test_wait_action_does_not_dispatch_to_node():
    loop, dispatched = _loop(
        [
            {"action": "wait", "seconds": 0.01, "reason": "等加载"},
            {"action": "done", "result": "ok"},
        ]
    )
    out = asyncio.run(loop.run("任务"))
    assert out["stop_reason"] == "done" and not dispatched  # wait 只 sleep,不派发


def test_action_failure_recorded_but_loop_continues():
    loop, dispatched = _loop(
        [
            {"action": "click", "x": 1, "y": 1, "reason": "试点"},
            {"action": "done", "result": "换个方式完成了"},
        ],
        fail_act=True,
    )
    out = asyncio.run(loop.run("任务"))
    # 单步失败进历史(模型下一步能看到),不当场崩掉整个循环
    assert out["stop_reason"] == "done"
    assert out["steps"][0]["success"] is False and out["steps"][0]["error"] == "act failed"


# ───────────────────── 解析容错 ─────────────────────


def test_parse_action_json_markdown_fence():
    assert _parse_action_json('```json\n{"action": "click", "x": 1}\n```') == {"action": "click", "x": 1}


def test_parse_action_json_with_prose():
    assert _parse_action_json('好的,下一步:\n{"action": "done", "result": "完成"}')["action"] == "done"


def test_parse_action_json_garbage_returns_none():
    assert _parse_action_json("我不知道该做什么") is None
    assert _parse_action_json("") is None


def test_unparseable_plan_stops_cleanly():
    @dataclass
    class _GarbageRouter:
        async def chat(self, messages=None, **kw):
            return _FakeResp(content="嗯……")

    async def _perceive():
        return "B64"

    async def _act(a, p, n):
        return {"success": True, "error": ""}

    loop = ComputerUseLoop(router=_GarbageRouter(), perceive_fn=_perceive, act_fn=_act)
    out = asyncio.run(loop.run("任务"))
    assert out["stop_reason"] == "plan_failed"


# ───────────────────── 白名单完备性 ─────────────────────


def test_allowlist_covers_all_mapped_actions():
    from core.computer_use_loop import _N36_ACTION

    assert set(_N36_ACTION.keys()) <= ALLOWED_ACTIONS


# ───────────────────── REST 路由 ─────────────────────


def test_route_rejects_bad_node_id():
    from core.routes.computer_use import ComputerUseTaskRequest, computer_use_task

    out = asyncio.run(computer_use_task(ComputerUseTaskRequest(instruction="x", node_id="../../etc/passwd")))
    assert out["stop_reason"] == "bad_request"


def test_openclawd_tool_schema_registered():
    from core.openclawd import _COMPUTER_USE_BUILTIN_TOOLS

    assert _COMPUTER_USE_BUILTIN_TOOLS[0]["function"]["name"] == "computer_use__run"
    assert "instruction" in _COMPUTER_USE_BUILTIN_TOOLS[0]["function"]["parameters"]["required"]
