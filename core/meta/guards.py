"""core/meta/guards.py — 元层的静态守卫：G6（算子不得改验证器）与 G10（不进热路径）。

两条都是「写下来会被绕过，所以做成能在 CI 上失败的东西」：

G6
==
Kernel 在运行时会拒绝越界的补丁（:func:`core.meta.kernel.write_surface_violation`）。这里
补上静态的一半：**可写面表与验证器表必须不相交**。有人往 ``WRITABLE_SURFACES`` 里加一个
落在 ``scripts/`` 或 ``tests/`` 下的前缀，运行时检查会先看到「在可写面内」—— 所以两张表
的关系必须在代码合入之前就钉死。

G10
===
每个请求都会经过的模块不得 import ``core.meta``，**无论模块级还是函数体里**；并且它们的
**模块级导入闭包**里也不得出现 ``core.meta``（间接也不行）。与冻结守则 R2.1–2.3 对
V4 / V6 / L4 的约束同档。每请求一次的分流判定因此不放在元层里。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

META_PACKAGE = "core.meta"

#: 每个请求都会经过的模块（G10）。
HOT_PATH_MODULES: Tuple[str, ...] = (
    "core/openclawd.py",
    "core/command_router.py",
    "core/desktop_presence_runtime.py",
    "core/presence_line.py",
    "core/lumiv_websocket_bridge.py",
    "galaxy_gateway/websocket_handler.py",
)


@dataclass(frozen=True)
class MetaGuardViolation:
    guard: str
    path: str
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return {"guard": self.guard, "path": self.path, "detail": self.detail}


def _mentions_meta(module: str) -> bool:
    return module == META_PACKAGE or module.startswith(META_PACKAGE + ".")


def direct_meta_imports(source: str) -> List[Tuple[int, str]]:
    """一段源码里所有指向 core.meta 的 import（任何作用域）与 importlib 字面量。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [(node.lineno, a.name) for a in node.names if _mentions_meta(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if _mentions_meta(node.module):
                hits.append((node.lineno, node.module))
            elif node.module == "core" and any(a.name == "meta" for a in node.names):
                hits.append((node.lineno, "core.meta"))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if fname in ("import_module", "__import__") and isinstance(value, str) and _mentions_meta(value):
                hits.append((node.lineno, value))
    return hits


def check_hot_path_isolation() -> List[MetaGuardViolation]:
    """G10：热路径模块不 import 元层，模块级导入闭包里也没有元层。"""
    violations: List[MetaGuardViolation] = []
    for rel in HOT_PATH_MODULES:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        for line, target in direct_meta_imports(path.read_text(encoding="utf-8")):
            violations.append(MetaGuardViolation("G10", f"{rel}:{line}", f"热路径模块 import 了 {target}"))

    from core.verification_ladder import build_dependency_index

    index = build_dependency_index()
    meta_nodes = {f for f in index.files if f.startswith("core/meta/")}
    meta_nodes |= {f + "#init" for f in meta_nodes if f.endswith("__init__.py")}
    reached = set(meta_nodes)
    frontier = list(meta_nodes)
    while frontier:
        current = frontier.pop()
        for dependent in index.top_dependents.get(current, ()):
            if dependent not in reached:
                reached.add(dependent)
                frontier.append(dependent)
    for rel in HOT_PATH_MODULES:
        if rel in reached:
            violations.append(
                MetaGuardViolation("G10", rel, "模块级导入闭包里出现了 core.meta —— 导入这个热路径模块就会加载元层")
            )
    return violations


def check_write_surfaces() -> List[MetaGuardViolation]:
    """G6：可写面表与验证器表不相交；阶段一 model 可写面为空。"""
    from core.meta.kernel import OPERATOR_SCOPES, VERIFIER_SURFACES, WRITABLE_SURFACES

    violations: List[MetaGuardViolation] = []
    for scope, prefixes in WRITABLE_SURFACES.items():
        for prefix in prefixes:
            for guarded in VERIFIER_SURFACES:
                if prefix.startswith(guarded) or guarded.startswith(prefix):
                    violations.append(
                        MetaGuardViolation("G6", prefix, f"{scope} 的可写面 {prefix!r} 与验证器 {guarded!r} 重叠")
                    )
    if WRITABLE_SURFACES.get("model"):
        violations.append(MetaGuardViolation("G6", "model", "Model-RSI 阶段一不开写，但 model 可写面非空"))
    if set(OPERATOR_SCOPES.values()) != set(WRITABLE_SURFACES):
        violations.append(MetaGuardViolation("G5", "OPERATOR_SCOPES", "算子作用域与可写面表的键不一致"))
    return violations


def check_meta_layer() -> List[MetaGuardViolation]:
    return check_write_surfaces() + check_hot_path_isolation()


__all__ = [
    "HOT_PATH_MODULES",
    "MetaGuardViolation",
    "check_hot_path_isolation",
    "check_meta_layer",
    "check_write_surfaces",
    "direct_meta_imports",
]
