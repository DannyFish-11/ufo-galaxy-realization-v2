"""L4 层的诚实性契约。

L4(``enhancements/`` + ``core/galaxy_main_loop_l4_enhanced.py``)是一套比
「常驻注意力循环 → OpenClawd ReAct」更早、且**从未接入主启动链**的自主实现。
它删不掉(``scripts/validate_runtime.py`` 与 ``audit/final_validation_probe.py``
都显式断言该模块存在),但它绝不能**看起来像在工作**。

本文件钉死三条:
1. 执行器遇到不认识的命令必须判失败,不许伪装成功;
2. 启动横幅不许拿"对象构造成功"冒充"循环在跑";
3. 真正的自主入口(常驻注意力循环)是默认开的。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── 1. 不许假成功 ──────────────────────────────────────────────────────


def _action(command: str):
    return SimpleNamespace(id="a1", subtask_id="s1", node_id=None, device_id=None, command=command, parameters={})


def test_unknown_command_raises_instead_of_faking_success():
    """规划器生成的命令执行器一个都不认识 —— 那必须是失败,不是成功。

    原实现返回 {"status": "unknown"} 且不抛异常,外层无条件包成
    ExecutionStatus.SUCCESS:每个动作都"成功"、成功率 100%、实际什么都没做,
    假成功还会流进监控与学习层。
    """
    from enhancements.execution.action_executor import ActionExecutor

    ex = ActionExecutor()
    for planner_command in (
        "web_search",
        "read_file",
        "write_file",
        "execute_command",
        "analyze_data",
        "synthesize_info",
        "device_control",
        "send_message",
    ):
        with pytest.raises(ValueError, match="不支持命令"):
            asyncio.run(ex._execute_command(_action(planner_command)))


def test_supported_commands_still_work():
    """收紧未知命令不能误伤本来就支持的两个。"""
    from enhancements.execution.action_executor import ActionExecutor

    ex = ActionExecutor()
    a = _action("log")
    a.parameters = {"message": "hi"}
    assert asyncio.run(ex._execute_command(a))["status"] == "logged"

    w = _action("wait")
    w.parameters = {"duration": 0}
    assert asyncio.run(ex._execute_command(w))["status"] == "completed"


def test_unknown_command_surfaces_as_failed_status():
    """端到端:未知命令经 execute_action 后必须是 FAILED,不是 SUCCESS。"""
    from enhancements.execution.action_executor import (
        ActionExecutor,
        ExecutionContext,
        ExecutionStatus,
    )

    ex = ActionExecutor()
    ctx = ExecutionContext(plan_id="p", goal_description="g", start_time=0.0, current_action_index=0, total_actions=1)
    result = asyncio.run(ex.execute_action(_action("web_search"), ctx))
    assert result.status is not ExecutionStatus.SUCCESS, "未知命令绝不能记成成功"


# ── 2. 横幅不许冒充 ────────────────────────────────────────────────────


def test_banner_does_not_claim_l4_loop_is_running():
    """l4_modules 是只写不读的字典;"已就绪"会让人以为自主循环在跑。"""
    src = (REPO / "launcher" / "services.py").read_text(encoding="utf-8")
    block = src.split("# ── L4 增强模块")[1].split("# (API 网关已在第一阶段绑定")[0]
    assert "后台增强层已就绪" not in block, "横幅仍在拿'对象构造成功'冒充'循环在跑'"
    assert "未接入主循环" in block, "横幅应如实说明 L4 未接入主循环"


def test_l4_modules_dict_is_still_write_only():
    """如实性的前提事实:若哪天真接上了,这条断言会失败,提醒来改横幅。"""
    src = (REPO / "launcher" / "services.py").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in src.splitlines() if "l4_modules" in ln]
    code = [ln for ln in lines if not ln.startswith("#")]

    #: 已知且允许的出现形态:字典定义、逐项赋值、横幅里用于计数的只读 getattr。
    allowed = (
        "self.l4_modules = {}",
        'self.l4_modules["',
        'getattr(l4, "l4_modules"',
    )
    unexpected = [ln for ln in code if not any(ln.startswith(a) or a in ln for a in allowed)]
    assert (
        not unexpected
    ), (
        "l4_modules 出现了新的用法 —— L4 可能已被真正接入主循环,"
        "请同步把启动横幅从'未接入主循环'改成如实措辞:\n" + "\n".join(unexpected)
    )


# ── 3. 真正的自主入口是开着的 ──────────────────────────────────────────


def test_real_autonomy_entry_is_enabled_by_default(monkeypatch):
    """L4 不承担自主性,承担的是常驻注意力循环 —— 它必须默认开。"""
    monkeypatch.delenv("GALAXY_AMBIENT_LOOP", raising=False)
    from core.ambient_attention_loop import ambient_loop_enabled

    assert ambient_loop_enabled() is True
