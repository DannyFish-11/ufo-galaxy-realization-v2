#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_shared_container_iteration_is_snapshotted.py

钉住：**带 await 的循环不许直接迭代会被并发改动的共享容器**。

这条缺陷的形状
==============
单线程 event loop 里，``await`` 就是让出点。下面这段在真实系统里随时会炸：

.. code-block:: python

    for node_id in self.nodes:              # ← 迭代的是活容器本身
        results[node_id] = await self.check_node_health(node_id)   # ← 在这里让出

让出期间另一个协程调用 ``register_node()`` 往 ``self.nodes`` 里塞一个键，
迭代恢复时立刻 ``RuntimeError: dictionary changed size during iteration``。

为什么它比看上去严重
--------------------
这些循环外面往往包着一个 ``while True`` 的常驻 supervisor，而 ``try/except``
**只包住那一次 await**（因为写的时候想的是"某个节点探测失败别影响别人"）。
RuntimeError 是 ``for`` 语句本身抛的，在 try 外面，于是一路逃出 ``while True``：

* ``core/node_registry.py`` 的 ``monitor_loop()`` —— 健康巡检永久停摆
* ``core/device_agent_manager.py`` 的 ``heartbeat_loop()`` —— 心跳永久停摆

进程还活着，日志里只有一条 task exception，之后**再也不会有健康检查/心跳**。
实测（复刻这两处的确切代码形状，巡检中途注册一台设备）::

    注册事件之前：完成 2 轮巡检，任务存活=True
    ❌ 监控任务已死：RuntimeError: dictionary changed size during iteration
       注册后又完成了 0 轮（应该有 ~10 轮）

set 同理（``Set changed size during iteration``）。list 更阴：不抛异常，
``remove()`` 让后续下标整体前移，于是**静默漏掉一个订阅者** —— 广播少发一份，
没有任何报错。

处置
====
一律先取快照再迭代（``list(...)``）。代价是一次浅拷贝，收益是循环期间容器怎么
变都不影响这一轮；本轮该发的照发，新来的下一轮自然会覆盖到。

为什么要有这个扫描测试
======================
修复的痕迹只是一个 ``list()``。它不带任何理由，下一个人做"清理"时会顺手拆掉，
而拆掉之后一切照常 —— 直到某天并发撞上那个窗口。所以判据不能只钉住"当时改对了"，
要钉住"这类写法不许再出现"。

判据（三条同时成立才算违规，与当时排查用的口径一致）：

1. 迭代目标是 ``self.X``（含 ``.items()/.values()/.keys()`` —— 它们是**视图**
   不是快照，第一版扫描漏了这一类，``core/routes/_shared.py`` 的设备广播就是
   这么漏掉的）；
2. 循环体里有 ``await``；
3. 同文件里有**元素级**改写（``add/remove/discard/append/pop/clear/del/[k]=v``）。
   整体重赋值（``self.x = [...]``，一般在 ``__init__``）不算 —— 那种容器不会在
   迭代中途变长变短。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_ROOTS = ("core", "galaxy_gateway", "contracts")

_VIEWS = {"items", "values", "keys"}
_ELEMENT_MUTATORS = {
    "add",
    "append",
    "clear",
    "discard",
    "extend",
    "insert",
    "pop",
    "remove",
    "setdefault",
    "update",
    "difference_update",
}


def _self_attr(node: ast.AST) -> str | None:
    """把迭代/改写目标归一成 ``self.X``；不是共享容器则 None。"""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _VIEWS
        and not node.args
    ):
        return _self_attr(node.func.value)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return f"self.{node.attr}"
    return None


def _element_mutations(tree: ast.AST) -> set[str]:
    """本文件里被**元素级**改写过的 self.X 集合。"""
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in _ELEMENT_MUTATORS:
                found.add(_self_attr(f.value) or "")
        elif isinstance(node, ast.AugAssign):
            found.add(_self_attr(node.target) or "")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript):  # self.x[k] = v，不含整体重赋值
                    found.add(_self_attr(t.value) or "")
        elif isinstance(node, ast.Delete):
            for t in node.targets:
                if isinstance(t, ast.Subscript):
                    found.add(_self_attr(t.value) or "")

    found.discard("")
    return found


def _scan(repo: pathlib.Path = _REPO, roots: tuple[str, ...] = _ROOTS) -> list[str]:
    violations: list[str] = []
    for root in roots:
        base = repo / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text("utf-8", errors="ignore"))
            except SyntaxError:  # pragma: no cover — 仓库里不该有
                continue
            mutated = _element_mutations(tree)
            if not mutated:
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.AsyncFunctionDef):
                    continue
                for loop in ast.walk(fn):
                    if not isinstance(loop, (ast.For, ast.AsyncFor)):
                        continue
                    key = _self_attr(loop.iter)
                    if key is None or key not in mutated:
                        continue
                    if not any(isinstance(n, ast.Await) for n in ast.walk(loop)):
                        continue
                    rel = path.relative_to(repo)
                    violations.append(f"{rel}:{loop.lineno}  {fn.name}()  for ... in {ast.unparse(loop.iter)}:")
    return violations


def test_no_await_loop_iterates_a_live_shared_container():
    """整仓零违规。新写一处直接迭代活容器的 await 循环，这条就红。"""
    violations = _scan()
    assert not violations, (
        "以下 await 循环直接迭代了会被并发改动的共享容器，"
        "迭代中途容器一变就 RuntimeError（list 则静默漏发）。\n"
        "改成先取快照：for x in list(self.xxx):\n\n  " + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# 区分度：上面那条必须真的会红，而不是扫描器扫了个寂寞
# ---------------------------------------------------------------------------

_KNOWN_SITES = [
    ("core/node_registry.py", "self.nodes"),
    ("core/device_agent_manager.py", "self._agents"),
    ("core/routes/_shared.py", "self.active_devices"),
    ("core/routes/_shared.py", "self.status_subscribers"),
    ("core/device_status_api.py", "self._websocket_clients"),
    ("core/adapters/udp_adapter.py", "self._peers"),
    ("galaxy_gateway/wake_event_bus.py", "self._subscribers"),
]


@pytest.mark.parametrize("relpath,container", _KNOWN_SITES)
def test_scanner_would_catch_it_if_the_snapshot_were_removed(relpath, container, tmp_path):
    """把 ``list()`` 拆掉，扫描器必须在**那一行**报出来。

    没有这一条的话，上面的"零违规"可能只是因为扫描器什么都扫不到。
    """
    src = (_REPO / relpath).read_text("utf-8")
    # 连着右括号一起去掉，否则剩个孤零零的 ")" 让文件语法就不成立，
    # 扫描器在 SyntaxError 上 continue，这条就会**假绿**。
    broken, n = re.subn(
        r"\bin list\(" + re.escape(container) + r"((?:\.\w+\(\))?)\)(\s*:)",
        r"in " + container + r"\1\2",
        src,
    )
    assert n, f"{relpath} 里没找到 list({container}...) —— 快照是不是被拆了？"
    ast.parse(broken)  # 拆完必须仍是合法 Python，否则测的不是扫描器而是语法错

    probe = tmp_path / "core"
    probe.mkdir()
    (probe / pathlib.Path(relpath).name).write_text(broken, "utf-8")

    hits = _scan(repo=tmp_path, roots=("core",))
    assert any(container in h for h in hits), f"拆掉快照后扫描器没报 {container}：{hits}"


# ---------------------------------------------------------------------------
# 行为面：扫描证明"快照写了"，这一节证明"快照有用"
#
# 用真实类跑，不用 mock —— 这类缺陷的成因就藏在真实容器类型上（dict/set 抛
# RuntimeError，list 静默漏发），换成 mock 就什么都测不出来了。
# ---------------------------------------------------------------------------


class _SlowNode:
    """健康探测要花点时间的假节点 —— 让出点必须真的存在，否则窗口根本不出现。"""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.metadata = type(
            "_Meta",
            (),
            {"health_score": 1.0, "error_message": None, "last_health_check": None, "status": None, "capabilities": []},
        )()

    async def health_check(self):
        await asyncio.sleep(0.01)
        return {"score": 1.0}


@pytest.mark.asyncio
async def test_node_health_sweep_survives_a_registration_mid_sweep():
    """巡检进行中注册一个节点，整轮巡检不许崩。

    这是 ``core/node_registry.py:519``。它跑在 ``start_health_monitor`` 的
    ``while True`` 里，而那里**没有** try —— 崩一次，健康巡检就永久停摆。
    """
    from core.node_registry import NodeRegistry

    reg = NodeRegistry()
    for i in range(6):
        reg.nodes[f"node{i}"] = _SlowNode(f"node{i}")

    sweep = asyncio.create_task(reg.check_all_health())
    await asyncio.sleep(0.015)  # 此刻正挂在某个节点的 health_check 上
    reg.nodes["late-arrival"] = _SlowNode("late-arrival")  # ← register_node 干的就是这件事

    results = await sweep  # 修复前：RuntimeError: dictionary changed size during iteration
    assert len(results) == 6, f"本轮该覆盖 6 个节点，实际 {sorted(results)}"
    assert "late-arrival" not in results, "快照语义：中途来的下一轮再管，不该混进这一轮"


class _FakeWS:
    def __init__(self, name: str):
        self.name = name
        self.received: list = []

    async def send_json(self, payload):
        await asyncio.sleep(0.005)
        self.received.append(payload)

    async def accept(self):
        pass


@pytest.mark.asyncio
async def test_status_broadcast_reaches_every_existing_subscriber():
    """广播途中有人订阅，**既有**订阅者必须一个不漏。

    这是 ``core/routes/_shared.py:244``。修复前 set 会抛
    ``Set changed size during iteration``，而它在 ``for`` 语句上、
    不在包住 ``send_json`` 的那个 try 里，于是整轮广播中断 ——
    实测 5 个既有订阅者里只有 2 个收到。
    """
    from core.routes._shared import RouteConnectionPool

    pool = RouteConnectionPool()
    existing = [_FakeWS(f"old{i}") for i in range(5)]
    for ws in existing:
        pool.status_subscribers.add(ws)

    task = asyncio.create_task(pool.broadcast_status({"kind": "probe"}))
    await asyncio.sleep(0.008)  # 广播已经发出去一两个，正挂在 send_json 上
    pool.status_subscribers.add(_FakeWS("newcomer"))

    await task
    missed = [ws.name for ws in existing if not ws.received]
    assert not missed, f"既有订阅者漏收：{missed}"
