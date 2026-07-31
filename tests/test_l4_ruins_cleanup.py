"""L4 废墟清理的收口契约。

## 删了什么、为什么只删这一层

所有者授权清理 L4 废墟。排查后**只删了能证明零引用的那一层**:

``integration/websocket_server.py``(549 行)——
  - 全仓**零 import**(``integration/__init__.py`` 只导出 event_bus);
  - **零测试依赖**;
  - 没有任何脚本 / CI / Makefile 启动它;
  - 只在几份历史报告里被当作独立入口提到(``python integration/websocket_server.py``)。

**没有删** ``core/galaxy_main_loop_l4_enhanced.py`` 与
``enhancements/reasoning/autonomous_planner.py``,因为仓库自己的治理层把前者
声明为 **canonical**:``scripts/validate_runtime.py``(跑在 node-governance
CI 门里)断言它必须可导入,``audit/final_validation_probe.py`` 把它列为
CRITICAL。删它等于当场打破一个今天就在跑的门,并推翻仓库自己写下的结论 ——
那是一个治理决策,不是清理动作。

**也没有删** ``AutonomousPlanner.update_plan``:它虽然零调用方,但自带完整的
设计分析(天然接入点在哪、为什么没接 —— ``ActionExecutor.execute_plan()``
从第 0 项重跑、不支持断点续跑,替换动作会让已成功的动作连副作用再跑一遍)。
那是**有意保留的预留 API**,不是忘了接的死代码;删掉等于把分析一起销毁。

## 这些用例守什么

删除必须是**干净**的 —— 不留断链、不留骗人的启动指令。仓库里已有先例
(``validate_runtime.py`` 对 post-PR-10 删除文件的断言),这里沿用同一做法。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DELETED = "integration/websocket_server.py"


def test_dead_entrypoint_is_gone():
    assert not (REPO / DELETED).exists(), f"{DELETED} 应已删除(全仓零引用)"


def test_nothing_imports_it():
    """删干净的第一层:没有任何代码还 import 它。"""
    offenders = []
    for path in REPO.rglob("*.py"):
        if any(part in {".git", "__pycache__", "node_modules", ".venv"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^\s*(from|import)\s+.*integration\.websocket_server", text, re.MULTILINE):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"仍有文件 import 已删除的模块: {offenders}"


def test_integration_package_still_imports():
    """删除不该把 integration 包本身弄坏 —— event_bus 仍有 80+ 个引用方。"""
    from integration import EventBus, event_bus  # noqa: F401


def test_no_doc_tells_you_to_run_it():
    """留着一条跑不通的启动指令,比留着死代码更坑人 —— 照做的人只会得到
    一个 FileNotFoundError,还以为是自己环境的问题。"""
    offenders = []
    for path in REPO.rglob("*.md"):
        if any(part in {".git", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # 已被注释掉的说明行不算指令
            if re.search(r"python\s+integration/websocket_server\.py", stripped):
                offenders.append(f"{path.relative_to(REPO)}: {stripped[:70]}")
    assert not offenders, "文档里仍教人启动一个已删除的文件:\n" + "\n".join(offenders)


def test_l4_module_docstring_no_longer_claims_a_server_drives_it():
    """L4 模块的文档原本写着"服务端:integration/websocket_server.py 通过
    get_galaxy_loop() 驱动"。那个服务端已经没了,这句话就成了假话 ——
    删代码不同步删说法,下一个人照样会以为它在跑。"""
    src = (REPO / "core" / "galaxy_main_loop_l4_enhanced.py").read_text(encoding="utf-8")
    head = src[: src.index('"""', 3)]

    # 断言的是**语义**,不是"别提那个文件名"—— 新文档恰恰要提它,才说得清
    # "原先由它驱动、现在没有了"。所以查的是那两句如实交代。
    assert "服务端:    **当前没有**" in head, "必须明说现在没有服务端在驱动它"
    assert "生产路径不可达" in head, "应如实写明本模块当前生产不可达"


# ── 保留物的理由也要钉住,免得下次被当成"漏删"顺手清掉 ──────────────


def test_canonical_l4_module_is_kept_because_governance_requires_it():
    """治理层声明它 canonical 且 CI 断言可导入 —— 这条用例是防止后来者
    (包括我自己)把"零生产调用方"当成"可以删"的理由。"""
    import importlib

    assert importlib.import_module("core.galaxy_main_loop_l4_enhanced") is not None

    validate = (REPO / "scripts" / "validate_runtime.py").read_text(encoding="utf-8")
    assert "core.galaxy_main_loop_l4_enhanced" in validate, "治理断言不该被一并删掉"


def test_update_plan_is_kept_and_still_explains_why_it_has_no_callers():
    """``update_plan`` 零调用方,但它是**有意保留的预留 API**,不是死代码。

    判据是它自己那段文档:说明了天然接入点、以及不接的真实阻碍
    (执行器不支持断点续跑)。哪天有人删掉方法或删掉这段说明,这里会红 ——
    因为那样一来"为什么没接"就又变回一个没人知道答案的问题了。
    """
    from enhancements.reasoning.autonomous_planner import AutonomousPlanner

    doc = AutonomousPlanner.update_plan.__doc__ or ""
    assert "当前全仓没有调用方" in doc
    assert "不支持从失败点续跑" in doc, "不接的真实原因必须留在文档里"


@pytest.mark.parametrize("method", ["create_plan", "update_decision_weights"])
def test_still_used_planner_methods_survive(method):
    """这两个有真实测试调用方,清理不该误伤。"""
    from enhancements.reasoning.autonomous_planner import AutonomousPlanner

    assert callable(getattr(AutonomousPlanner, method))
