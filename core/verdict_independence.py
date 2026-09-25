"""core/verdict_independence.py — 裁决不得由被裁决者自己报。

这道闸守的是什么
================
本仓在「一个任务执行完了算不算数」上有一整套确定性标准：13 个证据状态、4 个信任级别、
一个规范执法函数 :func:`core.execution_evidence_model.classify_execution_evidence`，
一处分数都没有。而在「一个代码补丁修好了没有」上，标准曾经是**一个 LLM 自己填的布尔值，
默认 true**：

.. code-block:: text

    core/openclawd.py          engineer__validate 的工具 schema 把 passed 声明为模型入参
    _dispatch_engineer_tool    passed = bool(arguments.get("passed", True))
    core/self_improvement.py   proposal.validation_passed = passed
                               → record_outcome() 打上 "validated" 标签写进知识库

提案者给自己判卷，判卷结果又被当成学习信号写回知识库。这在自我改进循环里是最致命的
那一类缺陷：循环会朝「让自己报通过」优化，而不是朝「真的修好」优化。

四个签名
========
全部用 AST 判定，不用正则：出现在注释、docstring 里的词不算。

======  ====================================================  ===================
签名    形状                                                  扫描范围
======  ====================================================  ===================
S1      工具 schema 的 ``parameters.properties`` 里有一个      全部 core/ 与
        布尔型的成败字段 —— 模型被要求**声明**自己成没成      galaxy_gateway/
S2      从模型给的参数里读成败字段（``arguments.get("passed")``）  同上
S3      函数把自己的**参数**直接写进裁决属性                  同上
        （``x.validation_passed = passed``）—— 按数据流判，
        改参数名绕不过去
S4      写裁决属性的模块没有引用规范执法函数                  推导出的写裁决模块
======  ====================================================  ===================

S1–S3 在引入时对全仓零噪音：各自只命中上面那条链上的一处。所以它们扫全仓，而不是一份
手写清单——**手写清单会腐烂**，新加的自我改进模块没人往清单里加，闸就悄悄不再覆盖它。

S4 的范围是推导出来的：凡是给裁决属性赋值的模块，要么引用执法函数，要么在
:data:`VERDICT_WRITER_EXEMPTIONS` 里写明为什么不需要。新模块一开始写裁决就会红，
直到有人对它做出判断。这与 :mod:`core.semantic_anchoring` 对「做检索的模块」的处理
是同一个做法。

什么不在射程内
==============
* **决策**不是**裁决**。``core/continuum/decision_gate.py`` 用
  ``value − interruption_cost − risk_cost`` 选 observe / hint / assist / execute，
  那是在行动之前挑一个动作，用确定性计算是对的；本闸只管「做完之后算不算数」。
* 各领域契约里**从事实推导出的** verdict（路由能力审计、离线回放排序契约）不是
  提案者自报，它们的豁免理由写在 :data:`VERDICT_WRITER_EXEMPTIONS` 里。
* 模型**提议**跑哪条验证命令是允许的；不允许的是模型**报告**命令的结果。
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 权威声明（本仓习语：哨兵字符串，供审计与测试引用）
# ---------------------------------------------------------------------------

VERDICT_INDEPENDENCE_IS_AUTHORITY: str = (
    "VERDICT_INDEPENDENCE::PROPOSER_MUST_NOT_SELF_CERTIFY: "
    "core/verdict_independence.py is the executable guard for the rule that a "
    "proposer never reports its own verdict.  Whether a patch, a validation run "
    "or a learning cycle 'passed' is observed by the harness (exit code, archived "
    "output) and adjudicated by core.execution_evidence_model."
    "classify_execution_evidence(); it is never read from a model's tool arguments."
)

PROPOSER_MUST_NOT_SELF_CERTIFY_POLICY: str = (
    "POLICY_VERDICT_1: a model may propose which verification to run; it may not "
    "report the verification's outcome.  Tool schemas must not declare a boolean "
    "success field as model input, and dispatchers must not read one from tool "
    "arguments."
)

VERDICT_FLOWS_THROUGH_ENFORCEMENT_POLICY: str = (
    "POLICY_VERDICT_2: every module that writes an execution/patch verdict attribute "
    "derives it from classify_execution_evidence(), or is listed in "
    "VERDICT_WRITER_EXEMPTIONS with a written reason."
)

# ---------------------------------------------------------------------------
# 判据词表
# ---------------------------------------------------------------------------

#: 成败字段名。出现在**模型入参**里就是自报成绩。
VERDICT_FIELD_NAMES: Set[str] = {
    "passed",
    "tests_passed",
    "validation_passed",
    "verified",
    "is_verified",
    "validated",
    "is_valid",
    "fixed",
    "fix_succeeded",
    "succeeded",
    "success",
}

#: 承载模型工具调用参数的变量名。
MODEL_ARGUMENT_NAMES: Set[str] = {
    "arguments",
    "args",
    "tool_args",
    "tool_arguments",
    "tool_input",
    "function_args",
    "call_args",
    "params",
}

#: 裁决属性名。写这些属性就是在下裁决。
VERDICT_ATTRIBUTE_NAMES: Set[str] = {
    "validation_passed",
    "tests_passed",
    "verified",
    "is_verified",
    "validated",
    "verdict",
    "trust_level",
}

#: 规范执法函数。S4 要求写裁决的模块引用它。
CANONICAL_ENFORCEMENT_FUNCTION: str = "classify_execution_evidence"

#: 工具 schema 里装入参定义的键。
_SCHEMA_PARAMETER_KEYS: Tuple[str, ...] = ("parameters", "input_schema")

#: 构造与反序列化不是裁决：把已有的裁决搬进对象，不是做出裁决。
_S3_EXEMPT_FUNCTIONS: Set[str] = {"__init__", "__post_init__", "from_dict"}

#: 默认扫描根。定义侧只看这两处，与 check_wiring 的口径一致。
DEFAULT_SCAN_ROOTS: Tuple[str, ...] = ("core", "galaxy_gateway")

# ---------------------------------------------------------------------------
# S4 豁免：写 verdict、但裁决对象不是执行结果的模块
# ---------------------------------------------------------------------------

VERDICT_WRITER_EXEMPTIONS: Dict[str, str] = {
    "core/mainline_routing_enforcement.py": (
        "路由能力审计的 ExplicitRouteVerdict：从设备已申报能力与所需能力的集合差算出，"
        "是派发**之前**的合法性判定，不是执行结果；没有提案者参与。"
    ),
    "core/offline_replay_ordering_contract.py": (
        "离线回放排序契约的 OfflineReplayContractVerdict：从已接收条目的计数"
        "（重复 / 过期 / 乱序 / 接受）确定性推出，是契约层面的陈述，不是执行结果。"
    ),
}

# ---------------------------------------------------------------------------
# 存量：引入本闸时已知、尚待修复的缺陷
#
# 键不含行号 —— 行号会漂，而「同一处缺陷还在不在」不该随格式化改变。
# 修掉一条就从这里删一条；测试断言扫描结果与这份清单**完全相等**，
# 所以多出一条（新缺陷）或少了一条却没删（清单过期）都会红。
#
# 引入时（M0）这里记着四条，全在 engineer__validate 那条链上：
#   S1 core/openclawd.py         engineer__validate.passed
#   S2 core/openclawd.py         _dispatch_engineer_tool:passed
#   S3 core/self_improvement.py  validate:validation_passed<-passed
#   S4 core/self_improvement.py  <module>
# M1 让验证由 harness 实跑、经 classify_execution_evidence() 定级之后清零。
# 修复前的代码仍能被本闸抓到，见 tests/test_verdict_independence.py 的 git 回放用例。
# ---------------------------------------------------------------------------

KNOWN_UNRESOLVED: Tuple[Tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class VerdictIndependenceFinding:
    """一处「提案者自报成绩」的签名命中。"""

    signature: str
    path: str
    line: int
    symbol: str
    detail: str

    @property
    def key(self) -> Tuple[str, str, str]:
        """不含行号的身份，用于与存量清单比对。"""
        return (self.signature, self.path, self.symbol)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# S1 — 工具 schema 把成败字段声明为模型入参
# ---------------------------------------------------------------------------


def _const_str(node: Optional[ast.AST]) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dict_get(node: ast.Dict, key: str) -> Optional[ast.AST]:
    for k, v in zip(node.keys, node.values):
        if _const_str(k) == key:
            return v
    return None


def _scan_tool_schemas(tree: ast.AST, path: str) -> List[VerdictIndependenceFinding]:
    findings: List[VerdictIndependenceFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        tool_name = _const_str(_dict_get(node, "name")) or "<anonymous>"
        for key in _SCHEMA_PARAMETER_KEYS:
            params = _dict_get(node, key)
            if not isinstance(params, ast.Dict):
                continue
            props = _dict_get(params, "properties")
            if not isinstance(props, ast.Dict):
                continue
            for prop_key, prop_val in zip(props.keys, props.values):
                field_name = _const_str(prop_key)
                if field_name not in VERDICT_FIELD_NAMES or not isinstance(prop_val, ast.Dict):
                    continue
                if _const_str(_dict_get(prop_val, "type")) != "boolean":
                    continue
                findings.append(
                    VerdictIndependenceFinding(
                        signature="S1",
                        path=path,
                        line=prop_key.lineno if prop_key is not None else node.lineno,
                        symbol=f"{tool_name}.{field_name}",
                        detail=f"工具 {tool_name!r} 要求模型声明布尔型成败字段 {field_name!r}",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# S2 / S3 — 按函数扫描
# ---------------------------------------------------------------------------


_FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _function_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_TYPES):
            yield node


def _own_nodes(func: ast.AST) -> Iterable[ast.AST]:
    """函数体里属于**这个**函数的节点：不下探嵌套函数（它们会作为自己被单独扫一遍）。

    用 ``ast.walk(func)`` 会让嵌套函数被父函数重复遍历，大文件上是平方级。
    """
    stack: List[ast.AST] = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _FUNCTION_TYPES):
            stack.extend(ast.iter_child_nodes(node))


def _read_verdict_from_model_args(node: ast.AST) -> Optional[Tuple[str, str]]:
    """``arguments.get("passed", ...)`` 或 ``arguments["passed"]`` → (变量名, 字段名)。"""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in MODEL_ARGUMENT_NAMES
        and node.args
    ):
        field_name = _const_str(node.args[0])
        if field_name in VERDICT_FIELD_NAMES:
            return node.func.value.id, field_name
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in MODEL_ARGUMENT_NAMES:
        field_name = _const_str(node.slice)
        if field_name in VERDICT_FIELD_NAMES:
            return node.value.id, field_name
    return None


def _unwrap_bool(value: ast.AST) -> ast.AST:
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "bool" and value.args:
        return value.args[0]
    return value


def _scan_functions(tree: ast.AST, path: str) -> List[VerdictIndependenceFinding]:
    findings: List[VerdictIndependenceFinding] = []
    for func in _function_nodes(tree):
        args = func.args  # type: ignore[attr-defined]
        params = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs} - {"self", "cls"}
        name = func.name  # type: ignore[attr-defined]
        for node in _own_nodes(func):
            hit = _read_verdict_from_model_args(node)
            if hit is not None:
                findings.append(
                    VerdictIndependenceFinding(
                        signature="S2",
                        path=path,
                        line=node.lineno,  # type: ignore[attr-defined]
                        symbol=f"{name}:{hit[1]}",
                        detail=f"{name}() 从模型参数 {hit[0]!r} 读取成败字段 {hit[1]!r}",
                    )
                )
            if name in _S3_EXEMPT_FUNCTIONS or not isinstance(node, ast.Assign):
                continue
            source = _unwrap_bool(node.value)
            if not (isinstance(source, ast.Name) and source.id in params):
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in VERDICT_ATTRIBUTE_NAMES:
                    findings.append(
                        VerdictIndependenceFinding(
                            signature="S3",
                            path=path,
                            line=node.lineno,
                            symbol=f"{name}:{target.attr}<-{source.id}",
                            detail=f"{name}() 把调用方给的参数 {source.id!r} 直接写进裁决属性 {target.attr!r}",
                        )
                    )
    return findings


def scan_source_for_self_certification(source: str, path: str = "<source>") -> List[VerdictIndependenceFinding]:
    """对一段源码跑 S1–S3。语法错误返回空（无法解析的文件不是本闸的职责）。"""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    return _scan_tool_schemas(tree, path) + _scan_functions(tree, path)


# ---------------------------------------------------------------------------
# S4 — 写裁决的模块必须走执法函数
# ---------------------------------------------------------------------------


def _writes_verdict_attribute(tree: ast.AST) -> Optional[int]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: Sequence[ast.AST] = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr in VERDICT_ATTRIBUTE_NAMES:
                return node.lineno
    return None


def _references_name(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
        if isinstance(node, ast.alias) and (node.name == name or node.name.endswith("." + name)):
            return True
    return False


def _iter_python_files(roots: Iterable[str]) -> Iterable[Path]:
    for root in roots:
        base = REPO_ROOT / root
        if base.is_dir():
            yield from sorted(base.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _may_contain_signature(source: str) -> bool:
    """纯文本预筛：不含任何触发子串的文件不可能命中，不必解析。

    可靠的前提是 black 格式化（CI 对 core/ 与 galaxy_gateway/ 强制）：四个签名在源码
    里必然留下 ``"properties"`` / ``arguments.get(`` / ``arguments[`` / ``.validation_passed``
    这类不带空白的子串。全仓 1066 个文件里约 117 个过得了这一关，扫描从 ~9 秒降到 1 秒内。
    """
    if '"properties"' in source or "'properties'" in source:
        return True
    if any(f"{name}.get(" in source or f"{name}[" in source for name in MODEL_ARGUMENT_NAMES):
        return True
    return any("." + attr in source for attr in VERDICT_ATTRIBUTE_NAMES)


def scan_repository(roots: Iterable[str] = DEFAULT_SCAN_ROOTS) -> List[VerdictIndependenceFinding]:
    """对仓库跑全部四个签名，按 (路径, 行号) 排序返回。"""
    findings: List[VerdictIndependenceFinding] = []
    for file_path in _iter_python_files(roots):
        rel = _rel(file_path)
        try:
            source = file_path.read_text(encoding="utf-8")
            if not _may_contain_signature(source):
                continue
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        findings.extend(_scan_tool_schemas(tree, rel))
        findings.extend(_scan_functions(tree, rel))
        line = _writes_verdict_attribute(tree)
        if line is None or rel in VERDICT_WRITER_EXEMPTIONS:
            continue
        if not _references_name(tree, CANONICAL_ENFORCEMENT_FUNCTION):
            findings.append(
                VerdictIndependenceFinding(
                    signature="S4",
                    path=rel,
                    line=line,
                    symbol="<module>",
                    detail=(
                        f"模块写裁决属性，但没有引用 {CANONICAL_ENFORCEMENT_FUNCTION}()，"
                        "也不在 VERDICT_WRITER_EXEMPTIONS 里"
                    ),
                )
            )
    return sorted(findings, key=lambda f: (f.path, f.line, f.signature))


def unresolved_findings(
    findings: Optional[List[VerdictIndependenceFinding]] = None,
) -> List[VerdictIndependenceFinding]:
    """扫描结果里**不在**存量清单上的那些 —— 这是闸真正要拦的新缺陷。"""
    known = set(KNOWN_UNRESOLVED)
    current = scan_repository() if findings is None else findings
    return [f for f in current if f.key not in known]


def stale_known_entries(
    findings: Optional[List[VerdictIndependenceFinding]] = None,
) -> List[Tuple[str, str, str]]:
    """存量清单里已经扫不到的条目 —— 修掉了却没从清单里删。"""
    current = scan_repository() if findings is None else findings
    present = {f.key for f in current}
    return [k for k in KNOWN_UNRESOLVED if k not in present]


def build_verdict_independence_report() -> Dict[str, Any]:
    """机器可读的完整报告，供脚本 ``--json`` 与状态端点使用。"""
    findings = scan_repository()
    return {
        "authority": VERDICT_INDEPENDENCE_IS_AUTHORITY,
        "policies": [PROPOSER_MUST_NOT_SELF_CERTIFY_POLICY, VERDICT_FLOWS_THROUGH_ENFORCEMENT_POLICY],
        "findings": [f.to_dict() for f in findings],
        "unresolved": [f.to_dict() for f in unresolved_findings(findings)],
        "stale_known_entries": [list(k) for k in stale_known_entries(findings)],
        "known_unresolved": [list(k) for k in KNOWN_UNRESOLVED],
        "exemptions": dict(VERDICT_WRITER_EXEMPTIONS),
    }


__all__ = [
    "CANONICAL_ENFORCEMENT_FUNCTION",
    "KNOWN_UNRESOLVED",
    "PROPOSER_MUST_NOT_SELF_CERTIFY_POLICY",
    "VERDICT_FLOWS_THROUGH_ENFORCEMENT_POLICY",
    "VERDICT_INDEPENDENCE_IS_AUTHORITY",
    "VERDICT_WRITER_EXEMPTIONS",
    "VerdictIndependenceFinding",
    "build_verdict_independence_report",
    "scan_repository",
    "scan_source_for_self_certification",
    "stale_known_entries",
    "unresolved_findings",
]
