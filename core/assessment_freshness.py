"""core/assessment_freshness.py —— 让过期的结论自己红

这个模块要解决的那件事
----------------------
2026-08-28 那次全仓评估里,最要紧的发现不是某个百分比,是**仓库对自己的判断已经
过期了四个月,而且每一处都带着一道绿灯**:

* ``audit/completion_matrix.json`` —— 日期 2026-04-29,20 个域的分数从没重推过。
  它的证据路径校验(``check_completion_matrix``)一直是绿的,因为**它查的是文件
  在不在**,35 条路径一条不缺。没有任何一处问过"那个分数还对吗"。
* ``docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md`` —— 把 ``task_cancel`` 列为唯一的
  P0 correctness failure,而 ``handle_task_cancel`` 早就写在
  ``task_lifecycle.py:1152``。
* ``core/runtime_closure_audit.py`` 的 ``_KNOWN_RESIDUAL_GAPS`` —— 文档明写"代码里
  这份才是权威",而它仍列 GAP-512-004 为开着,``scheduling_truth_harness.py``
  却明写 "closes GAP-512-004" 且 ``device_pool_manager.py:578`` 有真调用。

同一个缺陷,三处独立复现。再加上路线图那七个"阻塞中的设计问题"里有四个已经不成立
—— 四处。**判据以判据的形式被钉住之后,比没有它更难被质疑。**

为什么不是"自动重算分数"
------------------------
那做不到,硬做就是臆造。完成度矩阵原本的方法是人工 code-path tracing,
"这个域 65% 还是 80%"没有任何机械办法能算出来。

能做而且够用的是另一件事:**让"这条结论所依据的事实变了"自己报出来。**
结论仍然由人推导,但它不能再无声地烂在那儿。

判据长什么样
------------
每条结论声明若干**可机械复验的谓词**,以及记录当时它们的答案。谓词只有三种,
刻意保持得很少 —— 种类一多就会有人往里塞"差不多能表达"的东西,然后判据本身
开始漂:

``symbol_exists``
    某个符号(函数/类/常量名)在给定目录下的 ``.py`` 里出现过定义。
    回答的是"这个东西写了没有"。

``has_production_caller``
    某个符号在**生产代码**里被引用过(排除 tests/、排除定义它自己的那个文件、
    排除纯 re-export 的聚合模块)。回答的是"写了之后有没有人用" ——
    本仓反复踩的正是这一条:东西写好了、测过了、导出去了,一个调用点都没有。

``path_exists``
    文件或目录在不在。最弱的一种,只用于"这个东西还没被删掉"这类结论。

指纹不是文件哈希 —— 这一条很要紧
--------------------------------
第一版想过对 ``evidence_file`` 里的文件取哈希。那样会在**任何一次无关编辑**上
报红:改个注释、加个日志、格式化一遍,全都算"证据变了"。

一道天天误报的门,三周之内一定会被关掉或者被 ``--update-baseline`` 一路盖过去 ——
那时它比没有更糟,因为大家还以为它在守着。

所以指纹是**谓词的答案**,不是文件内容。改注释不会让 ``handle_task_cancel``
从不存在变成存在;而它真的被实现出来的那一天,这道门会响。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.AssessmentFreshness")

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 结论清单。人写、人改;这个模块只负责复验,不负责推导。
CLAIMS_FILE = REPO_ROOT / "config" / "assessment_claims.json"

#: 谓词种类。**刻意很少** —— 见模块头。
PREDICATE_KINDS: Tuple[str, ...] = ("symbol_exists", "has_production_caller", "path_exists")

#: 复验结论。``unverifiable`` 与 ``stale`` 必须分开:前者是"这条谓词问不出答案"
#: (目录没了、grep 挂了),后者是"问出来了,和记录的不一样"。混成一个的后果是
#: 一次环境故障会被读成"一批结论过期了",然后没人再信这道门。
VERDICTS: Tuple[str, ...] = ("fresh", "stale", "unverifiable")

#: 生产代码里**不算调用方**的目录/文件模式。
#: ``core/runtime/__init__.py`` 这类纯 re-export 的聚合模块要排掉 —— 把 re-export
#: 当成"有人用了",正好会让"写了没人用"这一整类问题验不出来(WebRTC 那次就是
#: 因为它出现在聚合模块里,粗看像是接上了)。
_NOT_A_CALLER = (
    "tests/",
    "/__pycache__/",
    "core/runtime/__init__.py",
)


@dataclass(frozen=True)
class PredicateResult:
    kind: str
    target: str
    scope: str
    expected: Optional[bool]
    actual: Optional[bool]
    detail: str = ""

    @property
    def verdict(self) -> str:
        if self.actual is None:
            return "unverifiable"
        return "fresh" if self.actual == self.expected else "stale"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "scope": self.scope,
            "expected": self.expected,
            "actual": self.actual,
            "verdict": self.verdict,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ClaimResult:
    claim_id: str
    source: str
    recorded_on: str
    statement: str
    predicates: List[PredicateResult]

    @property
    def verdict(self) -> str:
        kinds = {p.verdict for p in self.predicates}
        if "stale" in kinds:
            return "stale"
        if "unverifiable" in kinds:
            return "unverifiable"
        return "fresh"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "source": self.source,
            "recorded_on": self.recorded_on,
            "statement": self.statement,
            "verdict": self.verdict,
            "predicates": [p.to_dict() for p in self.predicates],
        }


# ══════════════════════════════════════════════════════════════════════════
# 谓词求值
# ══════════════════════════════════════════════════════════════════════════


def _grep(pattern: str, scope: str) -> Optional[List[str]]:
    """在 ``scope`` 下按正则搜。返回命中行;搜不动返回 ``None``(**问不出来**)。"""
    root = REPO_ROOT / scope
    if not root.exists():
        return None
    try:
        proc = subprocess.run(
            ["grep", "-rn", "--include=*.py", "-E", pattern, str(root)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001 — 搜不动就是问不出来,不猜
        logger.debug("grep 失败(%s @ %s): %s", pattern, scope, exc)
        return None
    if proc.returncode not in (0, 1):  # 1 = 没命中,是正常答案
        return None
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _symbol_exists(target: str, scope: str) -> Tuple[Optional[bool], str]:
    """这个符号定义出来了没有。"""
    hits = _grep(rf"^\s*(async\s+def|def|class)\s+{re.escape(target)}\b|^{re.escape(target)}\s*[:=]", scope)
    if hits is None:
        return None, "搜不动"
    return bool(hits), (hits[0][:160] if hits else "无定义")


def _has_production_caller(target: str, scope: str) -> Tuple[Optional[bool], str]:
    """这个符号在生产代码里被用过没有。

    排除 tests/、排除定义它自己的那些行、排除纯 re-export 聚合模块 ——
    见 :data:`_NOT_A_CALLER`。
    """
    hits = _grep(rf"\b{re.escape(target)}\b", scope)
    if hits is None:
        return None, "搜不动"

    def _is_caller(line: str) -> bool:
        path = line.split(":", 1)[0]
        rel = str(Path(path).resolve()).replace(str(REPO_ROOT) + "/", "")
        if any(frag in rel for frag in _NOT_A_CALLER):
            return False
        body = line.split(":", 2)[-1].lstrip()
        if body.startswith("#"):
            return False
        # 定义行本身不算调用
        return not re.match(rf"^(async\s+def|def|class)\s+{re.escape(target)}\b", body)

    callers = [h for h in hits if _is_caller(h)]
    return bool(callers), (callers[0][:160] if callers else f"{len(hits)} 处引用,但没有一处算调用方")


def _path_exists(target: str, _scope: str) -> Tuple[Optional[bool], str]:
    p = REPO_ROOT / target
    return p.exists(), ("在" if p.exists() else "不在")


_EVALUATORS = {
    "symbol_exists": _symbol_exists,
    "has_production_caller": _has_production_caller,
    "path_exists": _path_exists,
}


# ══════════════════════════════════════════════════════════════════════════
# 复验
# ══════════════════════════════════════════════════════════════════════════


def load_claims() -> List[Dict[str, Any]]:
    """读结论清单。读不到返回空表 —— 空表与"全都新鲜"必须可区分,见
    :func:`freshness_report` 里的 ``claims_loaded``。"""
    try:
        return list(json.loads(CLAIMS_FILE.read_text(encoding="utf-8"))["claims"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("结论清单读不到(%s): %s", CLAIMS_FILE, exc)
        return []


def verify_claim(claim: Dict[str, Any]) -> ClaimResult:
    """复验一条结论。"""
    results: List[PredicateResult] = []
    for pred in claim.get("predicates", []):
        kind = str(pred.get("kind", ""))
        target = str(pred.get("target", ""))
        scope = str(pred.get("scope", "core"))
        expected = pred.get("expected")
        evaluator = _EVALUATORS.get(kind)
        if evaluator is None or not target:
            results.append(PredicateResult(kind or "?", target, scope, expected, None, f"谓词种类不认识: {kind!r}"))
            continue
        actual, detail = evaluator(target, scope)
        results.append(PredicateResult(kind, target, scope, expected, actual, detail))

    return ClaimResult(
        claim_id=str(claim.get("id", "?")),
        source=str(claim.get("source", "")),
        recorded_on=str(claim.get("recorded_on", "")),
        statement=str(claim.get("statement", "")),
        predicates=results,
    )


def verify_all() -> List[ClaimResult]:
    return [verify_claim(c) for c in load_claims()]


def freshness_report() -> Dict[str, Any]:
    """给诊断面。"""
    claims = load_claims()
    results = [verify_claim(c) for c in claims]
    by_verdict: Dict[str, List[str]] = {v: [] for v in VERDICTS}
    for r in results:
        by_verdict[r.verdict].append(r.claim_id)
    return {
        # 0 条与"全都新鲜"是两回事 —— 清单没加载上时不该显示成一片绿。
        "claims_loaded": len(claims),
        "predicate_kinds": list(PREDICATE_KINDS),
        "verdicts": {v: len(by_verdict[v]) for v in VERDICTS},
        "stale": by_verdict["stale"],
        "unverifiable": by_verdict["unverifiable"],
        "stale_means": (
            "这条结论所依据的事实已经变了 —— **不是说结论一定错**,是说它必须被重新推导。"
            "推导仍然由人做;这道门只保证它不会无声地烂在那儿。"
        ),
        "unverifiable_means": ("谓词问不出答案(目录没了/搜不动),与「问出来了但对不上」是两回事,不能混为一谈。"),
        "results": [r.to_dict() for r in results],
    }
