#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_empty_return_is_distinguishable.py

钉住：**「真的没有」与「取不到」不许静默地取同一个值**。

这条缺陷的形状
==============
.. code-block:: python

    def get_last_attempt_log():
        try:
            ...
            if not history:
                return []          # ← 真的没有记录
            ...
        except Exception:
            return []              # ← 读取炸了，也是 []

消费方拿到 ``[]`` 无从区分，运维复盘界面显示"无降级记录"，而真相是"取不到记录"。
同一形状还出现在配置加载（文件损坏 ⇒ 被当成"没有配置"⇒ 静默跑默认值）、
供给状态查询（查询异常 ⇒ 被 L2 判成"无供给"⇒ 静默降级）等处。

为什么判据要这么窄
==================
整仓「except 里返回空容器」有 **334 处**，绝大多数完全正常：一次可选查询失败
返回 ``[]`` 本就是合理契约。334 不是缺陷数。真正成缺陷要三条同时成立：

1. except 分支返回空容器 / 0；
2. **同一个函数在正常路径上也返回同一个空值** —— 这才让两者取到同一个值；
3. 这个 except **不打日志** —— 打了至少现场查得到，剩下的只是接口表达力不足；
   不打就是彻底静默。

按这三条筛，334 → **17**，逐个看过后 9 条真、8 条按设计如此
（``_safe_list`` / ``tokenize`` / 若干 parser、normalizer —— 返回空就是它们的契约）。

处置
====
9 条一律让失败**留下痕迹**（warning 日志，带上下文）。其中
``_build_backend_supply_state`` 更进一步：改返回 ``None``（"没问出来"）以区别于
``{}``（"问过了，确实一个后端都没有"），调用方据此**跳过** L2 供给权威，而不是
把一次查询异常判成"无供给"后静默降级。

本测试做两件事：整仓扫描（新写一处就红）+ 对已修的几处做行为验证。
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_ROOTS = ("core", "galaxy_gateway", "contracts")

_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}

#: 按设计就该静默返回空的函数 —— 它们的**契约**就是"转不成就给空"，
#: 调用方也不需要区分。加白名单要写清楚为什么。
_BY_DESIGN = {
    ("contracts/mesh_session.py", "_safe_list"),
    ("contracts/runtime_recovery_reconciliation.py", "_safe_list"),
    ("core/cognitive/bm25_index.py", "tokenize"),
    ("contracts/mesh_membership.py", "from_device_formation_summary"),
    ("contracts/mesh_membership.py", "from_cross_device_routing_summary"),
    ("core/desktop_native_multimodal_ingress_contract.py", "_extract_mm"),
    ("core/desktop_native_multimodal_ingress_contract.py", "_build_android_perception_ingress_snapshot"),
    ("galaxy_gateway/android/handlers/registration.py", "_normalize_assimilation_capabilities"),
}


def _empty_kind(node) -> str | None:
    """这个返回值是不是"空"；是就给出归一化写法，否则 None。"""
    if isinstance(node, ast.List) and not node.elts:
        return "[]"
    if isinstance(node, ast.Dict) and not node.keys:
        return "{}"
    if isinstance(node, ast.Tuple) and not node.elts:
        return "()"
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool) and node.value in (0, 0.0):
        return "0"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("set", "list", "dict")
        and not node.args
    ):
        return f"{node.func.id}()"
    return None


def _handler_logs(handler: ast.ExceptHandler) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _LOG_METHODS
        for n in ast.walk(handler)
    )


def _scan(repo: pathlib.Path = _REPO, roots: tuple[str, ...] = _ROOTS) -> list[str]:
    violations: list[str] = []
    for root in roots:
        base = repo / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text("utf-8", errors="ignore"))
            except SyntaxError:  # pragma: no cover
                continue
            rel = str(path.relative_to(repo))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if (rel, fn.name) in _BY_DESIGN:
                    continue

                handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
                if not handlers:
                    continue
                in_handler = {id(n) for h in handlers for n in ast.walk(h)}

                # 正常路径（不在任何 except 里）返回过哪些空值
                normal_empty = {
                    kind
                    for n in ast.walk(fn)
                    if isinstance(n, ast.Return)
                    and n.value is not None
                    and id(n) not in in_handler
                    and (kind := _empty_kind(n.value))
                }
                if not normal_empty:
                    continue

                for h in handlers:
                    if _handler_logs(h):
                        continue
                    for n in ast.walk(h):
                        if not isinstance(n, ast.Return) or n.value is None:
                            continue
                        kind = _empty_kind(n.value)
                        if kind and kind in normal_empty:
                            violations.append(f"{rel}:{n.lineno}  {fn.name}() -> {kind}")
    return violations


def test_no_silently_ambiguous_empty_return():
    """整仓零违规。"""
    violations = _scan()
    assert not violations, (
        "以下函数在 except 里静默返回了一个**正常路径也会返回**的空值，"
        "消费方无从区分「真的没有」与「取不到」。\n"
        "至少 log 一条带上下文的 warning；调用方需要据此改变决策的，"
        "改成返回 None 之类可区分的值；确属契约如此的，加进 _BY_DESIGN 并写清理由。\n\n  " + "\n  ".join(violations)
    )


def test_the_scanner_is_not_vacuous(tmp_path):
    """区分度：扫描器必须真的认得出这个形状，否则上面那条只是空转。"""
    probe = tmp_path / "core"
    probe.mkdir()
    (probe / "m.py").write_text(
        "def look(x):\n"
        "    try:\n"
        "        if not x:\n"
        "            return []\n"
        "        return list(x)\n"
        "    except Exception:\n"
        "        return []\n",
        "utf-8",
    )
    hits = _scan(repo=tmp_path, roots=("core",))
    assert any("look()" in h for h in hits), f"扫描器没认出这个形状：{hits}"


def test_a_logged_handler_is_not_flagged(tmp_path):
    """区分度的另一半：加了日志就不该再报，否则修法无从落地。"""
    probe = tmp_path / "core"
    probe.mkdir()
    (probe / "m.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def look(x):\n"
        "    try:\n"
        "        if not x:\n"
        "            return []\n"
        "        return list(x)\n"
        "    except Exception as exc:\n"
        "        logger.warning('failed: %s', exc)\n"
        "        return []\n",
        "utf-8",
    )
    assert not _scan(repo=tmp_path, roots=("core",))


# ---------------------------------------------------------------------------
# 行为面：最要紧那条不是"补个日志"，是让调用方**真的分得开**
# ---------------------------------------------------------------------------


class _BoomBackend:
    """get_status() 会炸的后端 —— 复刻供给状态查询失败。"""


def test_supply_state_query_failure_is_not_no_supply():
    """`{}`（确实没有后端）与 `None`（没问出来）必须分开。

    修复前两者同取 `{}`，L2 收到零 provider ⇒ is_satisfied=False ⇒ 静默降级，
    而后端可能好端端的。
    """
    from core.unified.llm_router import UnifiedLLMRouter

    router = object.__new__(UnifiedLLMRouter)

    # ① 没有后端 —— 这是"确实没有"（确定的空），必须是 {} 而不是 None，
    #    否则两个方向就又混成一个值了
    router._backend = None
    assert router._build_backend_supply_state() == {}

    # ② 后端在，但查询抛异常 —— 必须是 None，不能是 {}
    router._backend = _BoomBackend()
    router.get_status = lambda: (_ for _ in ()).throw(RuntimeError("status blew up"))
    assert router._build_backend_supply_state() is None, "查询失败仍返回 {} —— L2 会把它当成'无供给'"


def test_l2_consult_skips_instead_of_declaring_no_supply():
    """供给状态问不出来时，调用方必须**跳过** L2，而不是判"不满足"后降级。"""
    from core.unified.llm_router import UnifiedLLMRouter

    src = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(UnifiedLLMRouter._consult_l2_supply))))
    assert "supply_state is None" in src, "调用方没有区分'没问出来'与'没有供给'"


@pytest.mark.parametrize(
    "modpath,funcname",
    [
        ("core.runtime_truth_governance", "load_json_payload"),
        ("core.multimodal_runtime_profile", "_load_root_config_defaults"),
        ("core.container_runtime", "load_choice_record"),
    ],
)
def test_config_load_failures_leave_a_trace(modpath, funcname):
    """配置类加载：文件损坏与"文件不存在"上面同取 {}，至少要留下痕迹。

    否则一份坏掉的配置会让系统静默退回全默认值，现场毫无线索。
    """
    import importlib

    mod = importlib.import_module(modpath)
    fn = getattr(mod, funcname)
    src = ast.unparse(ast.parse(inspect.getsource(fn)))
    assert "logger" in src, f"{modpath}.{funcname} 的失败路径仍然完全静默"
