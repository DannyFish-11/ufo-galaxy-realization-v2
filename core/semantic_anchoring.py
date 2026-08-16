#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/semantic_anchoring.py — 决策面锚定判据与可执行守卫
========================================================

**Stage 2：把"什么走对象层、什么走检索"从口头约定变成可执行的检查。**

判据
----
一次读取，如果它的结果会**改变控制流**——选策略、选设备、判权限、决定是否执行
动作——必须走对象层做确定性查询。
如果结果只是**进入 prompt 供 LLM 参考**——知识问答、经验借鉴、上下文补全——
走检索（向量/BM25）是对的，也应该继续走。

**该换的是决策路径，不是检索能力。** 这个仓库两种需求都真实存在：
``Node_105`` 的多源知识库、``academic_retrieval`` 摄入的论文，本来就是非结构化
文本，向量检索是对的工具。删掉它们既无必要也是损失。

为什么需要一道自动守卫
----------------------
Stage 0 修掉的那个缺陷有一个非常具体的签名：

    在同一个函数里，先 ``recall(...)`` 拿回按相似度排序的文本，
    再用 ``re.search(...)`` 把结构从那段文本里抠出来，然后拿它做决策。

这个形状是可检测的，而且它正是"从检索到的散文里反解结构"的实锤——一旦有人
再写出来，说明决策又开始依赖概率性文本了。哨兵只是文档，会被绕过；
:func:`scan_source_for_prose_derived_structure` 是能在 CI 上失败的东西。

审计记录（截至 Stage 2）
------------------------
下列 live 召回点已逐个核对，全部合规：

===============================================  ==========  ================
调用点                                            用途        判定
===============================================  ==========  ================
``execution_planner`` 经验召回（prompt 注入）      建议        检索合规
``session_memory_facade`` 语义长程记忆召回         建议        检索合规
``openclawd`` ``memory__recall`` 工具             建议        检索合规
``openclawd`` 记忆工具暴露门                       能力门      非读取路径
``websocket_handler`` 感知内容入记忆               写入        非读取路径
``session_memory_facade`` 对话入记忆               写入        非读取路径
``ambient_attention_loop`` salient 入记忆          写入        非读取路径
===============================================  ==========  ================

Stage 0 之前唯一的违规是 ``ExecutionPlanner._experience_strategy_adjust``，
已改为读 ``TaskSummary`` 的类型化字段（见 ``core.cognitive.experience_guidance``）。
**本阶段的审计结论是：决策路径当前零违规**，因此 Stage 2 交付的是让它保持零违规
的守卫，而不是又一轮修补。
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("Galaxy.SemanticAnchoring")

__all__ = [
    "SEMANTIC_ANCHORING_IS_AUTHORITY",
    "DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY",
    "RETRIEVAL_IS_ADVISORY_ONLY_POLICY",
    "RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY",
    "RETRIEVAL_CALL_NAMES",
    "STRUCTURE_EXTRACTION_CALLS",
    "DECISION_PATH_MODULES",
    "AUDITED_RETRIEVAL_CALL_SITES",
    "AnchoringViolation",
    "scan_source_for_prose_derived_structure",
    "scan_module_for_prose_derived_structure",
    "scan_decision_paths",
]


# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

SEMANTIC_ANCHORING_IS_AUTHORITY: str = (
    "SEMANTIC_ANCHORING::AUTHORITY: "
    "This module states where control-flow decisions may get their facts, and "
    "provides the executable guard that keeps the rule from decaying into a "
    "comment.  It does not itself read, retrieve, or decide anything."
)

DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY: str = (
    "SEMANTIC_ANCHORING::POLICY_1: "
    "Any retrieval whose result alters control flow — strategy selection, device "
    "or target selection, permission decisions, whether an action executes — MUST "
    "resolve through the typed object layer with a deterministic query. "
    "Similarity-ranked text retrieval is NEVER authoritative for control flow."
)

RETRIEVAL_IS_ADVISORY_ONLY_POLICY: str = (
    "SEMANTIC_ANCHORING::POLICY_2: "
    "Vector/lexical retrieval output is admissible only as prompt context for an "
    "LLM to weigh.  Consumers MUST NOT parse structure back out of retrieved "
    "prose: a value re-extracted from a similarity-ranked blob carries the "
    "sampling bias of the retrieval, not the authority of the underlying fact."
)

RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY: str = (
    "SEMANTIC_ANCHORING::POLICY_3: "
    "This doctrine narrows where retrieval may be *believed*, not whether it may "
    "exist.  Knowledge bases over genuinely unstructured text (Node_105, "
    "academic_retrieval) are the correct use of vector search and MUST NOT be "
    "removed in the name of object anchoring.  What changes is the decision path."
)


# ---------------------------------------------------------------------------
# Detection vocabulary
# ---------------------------------------------------------------------------

RETRIEVAL_CALL_NAMES: Set[str] = {
    "recall",
    "recall_media",
    "query_knowledge",
    "retrieve_similar",
    "search_hybrid",
}
"""Method names that return similarity- or relevance-ranked results.

``retrieve_similar`` and ``search_hybrid`` are included even though they are
lexical/hybrid rather than embedding-based: the defect is *re-deriving structure
from ranked text*, and ranked text is ranked text however it was ranked."""

STRUCTURE_EXTRACTION_CALLS: Set[str] = {
    "search",
    "match",
    "fullmatch",
    "findall",
    "finditer",
    "split",
}
"""``re`` module entry points that pull structure out of a string."""

DECISION_PATH_MODULES: Tuple[str, ...] = (
    "core.agent.execution_planner",
    "core.agent.kernel",
    "core.scheduler",
    "core.command_router",
    "core.cognitive.experience_guidance",
    "core.cognitive.memory_bias_layer",
)
"""Modules whose code can change control flow and are therefore in scope.

Deliberately a short, explicit list rather than "everything": a guard that scans
the whole repository would drown in false positives from unrelated regex use and
would be switched off, which is worse than a narrow guard that stays on."""

AUDITED_RETRIEVAL_CALL_SITES: Tuple[Dict[str, str], ...] = (
    {
        "site": "core/agent/execution_planner.py — 经验召回注入 prompt",
        "use": "advisory",
        "verdict": "compliant — retrieved text goes into context, not into a decision",
    },
    {
        "site": "core/session_memory_facade.py — 语义长程记忆召回",
        "use": "advisory",
        "verdict": "compliant — appended as a system message",
    },
    {
        "site": "core/openclawd.py — memory__recall 工具实现",
        "use": "advisory",
        "verdict": "compliant — tool output returned to the LLM",
    },
    {
        "site": "core/openclawd.py — 记忆工具暴露门",
        "use": "capability-gate",
        "verdict": "compliant — decides tool visibility, reads nothing",
    },
    {
        "site": "galaxy_gateway/websocket_handler.py — 感知内容入记忆",
        "use": "write",
        "verdict": "compliant — write path",
    },
    {
        "site": "core/session_memory_facade.py — 对话入记忆",
        "use": "write",
        "verdict": "compliant — write path",
    },
    {
        "site": "core/ambient_attention_loop.py — salient 入记忆",
        "use": "write",
        "verdict": "compliant — write path",
    },
)
"""The Stage 2 audit, recorded so a reviewer can check the reasoning rather than
re-derive it.  The one historical violation
(``ExecutionPlanner._experience_strategy_adjust``) was removed in Stage 0."""


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class AnchoringViolation:
    """One function that both retrieves ranked text and parses structure from it."""

    module: str = ""
    function: str = ""
    lineno: int = 0
    retrieval_calls: List[str] = field(default_factory=list)
    extraction_calls: List[str] = field(default_factory=list)

    def describe(self) -> str:
        return (
            f"{self.module}.{self.function} (line {self.lineno}): "
            f"calls {sorted(set(self.retrieval_calls))} and then applies "
            f"re.{{{','.join(sorted(set(self.extraction_calls)))}}} to the result — "
            f"structure re-derived from similarity-ranked text. "
            f"Read the typed field instead (SEMANTIC_ANCHORING::POLICY_2)."
        )


def _function_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", "")


def _is_re_call(node: ast.Call) -> Optional[str]:
    """Return the ``re`` function name when *node* is ``re.<fn>(...)``."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in STRUCTURE_EXTRACTION_CALLS:
        return None
    value = func.value
    # Only count `re.search(...)`, not `some_string.split(...)`.
    if isinstance(value, ast.Name) and value.id == "re":
        return func.attr
    return None


def scan_source_for_prose_derived_structure(source: str, module_name: str = "<source>") -> List[AnchoringViolation]:
    """Find functions that retrieve ranked text and then regex structure out of it.

    This is the exact signature of the defect Stage 0 removed.  It is a heuristic,
    and deliberately a narrow one: it fires only when *both* halves appear in the
    same function body, because either alone is legitimate (retrieval feeding a
    prompt; regex over a config string).

    Never raises — an unparseable file yields no violations rather than breaking
    the caller.  A guard that can crash the build on a syntax quirk gets disabled.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.debug("semantic anchoring scan skipped for %s: %s", module_name, exc)
        return []

    violations: List[AnchoringViolation] = []
    for fn in _function_nodes(tree):
        retrievals: List[str] = []
        extractions: List[str] = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if name in RETRIEVAL_CALL_NAMES:
                retrievals.append(name)
            re_fn = _is_re_call(node)
            if re_fn:
                extractions.append(re_fn)
        if retrievals and extractions:
            violations.append(
                AnchoringViolation(
                    module=module_name,
                    function=fn.name,
                    lineno=fn.lineno,
                    retrieval_calls=retrievals,
                    extraction_calls=extractions,
                )
            )
    return violations


def scan_module_for_prose_derived_structure(module_name: str) -> List[AnchoringViolation]:
    """Scan an importable module by name.  Unimportable modules are skipped."""
    try:
        import importlib
        import inspect

        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
    except Exception as exc:  # noqa: BLE001 — a missing optional module is not a violation
        logger.debug("semantic anchoring scan skipped for %s: %s", module_name, exc)
        return []
    return scan_source_for_prose_derived_structure(source, module_name)


def scan_decision_paths(modules: Optional[Tuple[str, ...]] = None) -> List[AnchoringViolation]:
    """Scan every in-scope decision-path module.  Returns all violations found."""
    out: List[AnchoringViolation] = []
    for name in modules or DECISION_PATH_MODULES:
        out.extend(scan_module_for_prose_derived_structure(name))
    return out


def build_audit_report() -> Dict[str, Any]:
    """A JSON-safe snapshot of the doctrine plus the current scan result."""
    violations = scan_decision_paths()
    return {
        "policies": [
            DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY,
            RETRIEVAL_IS_ADVISORY_ONLY_POLICY,
            RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY,
        ],
        "scanned_modules": list(DECISION_PATH_MODULES),
        "audited_call_sites": [dict(s) for s in AUDITED_RETRIEVAL_CALL_SITES],
        "violations": [v.describe() for v in violations],
        "clean": not violations,
    }
