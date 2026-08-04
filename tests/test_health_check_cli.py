#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_health_check_cli.py — ``python -m core.health_check`` 不许再静默成功

真机实测过的问题：该模块**没有** ``__main__`` 守卫，于是
``python -m core.health_check`` 会**静默 exit 0 而什么也不做** —— 无输出、无副作用、
返回码 0。

静默的成功比崩溃更糟。模块名（health_check）明摆着在邀请人当 CLI 用，而"跑了、
绿了、什么都没查"会让人以为系统健康。自动化脚本尤其：
``python -m core.health_check && deploy`` 会无条件放行。

顺带钉住"五处健康检查"的**分工**——它们不是一件事的五份拷贝，把它们强行合并
只会让四类调用方互相牵制。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from core.health_check import HEALTHY_STATUS, HealthChecker

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "core.health_check", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )


def test_cli_actually_produces_output():
    """最基本的一条：它必须**做点什么**。

    此前这条会失败 —— stdout 完全为空而返回码是 0。
    """
    r = _run_cli()
    assert r.stdout.strip(), f"python -m core.health_check 什么也没输出（rc={r.returncode}）"


def test_cli_emits_valid_json():
    r = _run_cli()
    payload = json.loads(r.stdout)
    assert "status" in payload
    assert "system_metrics" in payload, "深度检查该带系统指标"


def test_cli_exit_code_reflects_the_verdict_not_merely_completion():
    """退出码来自**结论**，不是"跑完了就算成功"。

    这正是原问题的核心：原来它永远 0，与系统实际状态无关。
    """
    r = _run_cli()
    payload = json.loads(r.stdout)
    expected = 0 if payload.get("status") == HEALTHY_STATUS else 1
    assert r.returncode == expected, f"status={payload.get('status')} 却返回 {r.returncode}"


def test_exit_code_maps_the_same_way_as_the_ready_route():
    """CLI 的 0/1 与 ``/health/ready`` 的 200/503 必须**同一条判据**。

    我第一版就是另列了一张 ``("healthy","ok","alive")`` 同义词表，而
    ``check_readiness()`` 的正常返回值是 ``"ready"`` —— 不在表里，于是一台
    健康的机器被判成 exit 1。判据分散写就会这样漂，所以收敛成
    :data:`~core.health_check.HEALTHY_STATUS` 一个常量。
    """
    import ast

    src = (REPO_ROOT / "core" / "health_check.py").read_text(encoding="utf-8")
    # 三处消费方都必须引用常量，而不是各写一个 "ready" 字面量
    assert src.count("HEALTHY_STATUS") >= 4, "常量该被定义处 + 三个消费方各引用一次"

    # 按 AST 找"与字面量 'ready' 做比较"的表达式。
    # 不能搜子串 —— 这一段判据的**说明文字**里就写着 `== "ready"`（记录我改错的
    # 那一版）。扫描器读到自己写的字，和 launcher 那轮遇到的是同一类自指陷阱。
    bare = [
        node.lineno
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Compare)
        and any(isinstance(c, ast.Constant) and c.value == "ready" for c in node.comparators)
    ]
    assert not bare, f"不许再有裸的 'ready' 字面量比较（行号：{bare}）"


async def _readiness_status() -> str:
    return (await HealthChecker().check_readiness())["status"]


def test_healthy_status_is_what_check_readiness_actually_returns():
    """自证：常量不是凭空写的，而是 ``check_readiness`` 真正产出的那个值。

    没有这条，把常量改成任意字符串后上面那些测试仍然自洽地全绿。
    """
    import asyncio

    assert asyncio.run(_readiness_status()) == HEALTHY_STATUS


# ---------------------------------------------------------------------------
# 分工：四件事，不是一件事的四份拷贝
# ---------------------------------------------------------------------------


def test_the_four_health_surfaces_all_exist_and_are_distinct():
    """ "健康检查有五处"这个说法容易被读成"有五份重复"，然后有人去合并/删除。

    实际是四件不同的事，各有各的调用方：

    - ``launcher/health_checks.py`` 启动面：启动完成后跑一次
    - ``health_monitor.py``        独立的常驻 FastAPI 服务
    - ``core/health_check.py``     路由工厂：给 app 装 /health/*
    - ``scripts/health_check.sh``  运维面：从**进程外**探端口与 HTTP
    """
    assert (REPO_ROOT / "launcher" / "health_checks.py").is_file()
    assert (REPO_ROOT / "health_monitor.py").is_file()
    assert (REPO_ROOT / "core" / "health_check.py").is_file()
    assert (REPO_ROOT / "scripts" / "health_check.sh").is_file()


def test_core_health_check_is_a_route_factory_first():
    """本模块的**主要**身份仍是路由工厂 —— 补 ``__main__`` 不改变这一点。"""
    from core.health_check import create_health_routes

    assert callable(create_health_routes)


def test_division_of_labour_is_written_down():
    """分工必须写在代码里。

    它此前不在任何地方 —— 所以"看着像重复"才会反复引发合并/误删的冲动。
    """
    src = (REPO_ROOT / "core" / "health_check.py").read_text(encoding="utf-8")
    for surface in ("launcher/health_checks.py", "health_monitor.py", "scripts/health_check"):
        assert surface in src, f"分工说明里漏了 {surface}"
