"""core/verification_ladder.py — 分级验证阶梯：改了什么，就只验会被它影响的那些。

为什么需要它
============
此前验证只有一档：全量 46 个检查、4 个测试分片，每片 8–11 分钟（串行约 40 分钟）。
一个每次提案都过全量的改进循环，理论上限是每小时 5 轮 —— 那不是持续改进，是偶尔
改进。这是架构书 R8 说的「决定『持续』两个字能不能成立的那一项」。

四档
====
======  ==================================================  ====================
档位    内容                                                实测量级
======  ==================================================  ====================
L0      受影响的测试文件（依赖图反向选择）                  秒级到一分钟
L1      L0 + 全部静态守卫门（纯 AST，不装依赖）             一到两分钟
L2      ``test:fast`` 全量（CI 的 4 个分片）                并行约 11 分钟
L3      全量 CI（46 个检查）                                只在合入主干时
======  ==================================================  ====================

架构书里写的「L1 = test:fast ~1 分钟、L2 = 相关分片 ~3 分钟」是按猜测写的，与 CI
实测不符：``test:fast`` 本身就是四片之和。这里按实测重新划分，意图不变 ——
**绝大多数提案止步于 L0/L1**，L3 永远是合入主干的最后一道门。

依赖语义：模块级无限传递，懒导入只算一跳
========================================
这是整个模块最要紧的一个判断，所以单独说。

本仓是一个到处都是**懒导入**的大单体（``import core`` 实测只加载 3 个模块，其余都藏在
函数体里）。若把「所有 import 的传递闭包」当依赖，任何两个模块几乎都连得上，L0 会
退化成全量 —— 实测改 ``core/self_improvement.py`` 选中了全部 1262 个测试文件。

贴近运行时的语义是：

* **模块级 import**（含类体、``try``、``if``）在导入时必然执行 → 无限传递；
* 导入子模块时父包 ``__init__`` 被执行，但只执行它的**模块级**代码 → 父包记为
  ``#init`` 伪节点，只带模块级依赖；显式用到包本身（``from core import get_x``）才
  依赖整个 ``__init__.py``；
* **函数体里的懒导入**只在那个函数被调用时执行。测试会直接调用它导入的模块里的函数，
  所以只算**一跳**：测试直接依赖的模块 A，以及 A 的懒导入 B（连同 B 的模块级闭包）。

再深的懒导入链（A.f 调 B.g，g 里再懒导入 C）静态无法确定，这是本选择器已知的盲区，
由 ``scripts/replay_verification_ladder.py`` 的故障注入回放量化，并由阶梯本身兜底：L0 只是快速
过滤，合入主干永远要过 L3。

其余几种边：

* ``importlib.import_module("core.x")`` / ``__import__("core.x")`` 的字面量参数；
* **测试文件**里字符串中的点号模块名与仓库路径：``patch("core.x.run")``、
  ``"scripts/check_x.py"``（子进程跑脚本：依赖脚本本身与它的一跳懒导入）。生产代码里
  的这类字符串多半是文档与登记表，不算；
* **conftest**：受影响时，它目录下所有测试都受影响；
* **非 Python 文件**（js / html / yaml / json）：源码里出现它文件名的 .py 视作读它的人
  （``_RENDERER / "app.js"`` 这种拼接写法只能靠文件名认）。

什么时候 L0 不作数
==================
``escalate_reason`` 非空时 L0 的结论**不可信**，调用方必须上更高一档：

* 改了全局配置（``pytest.ini`` / ``pyproject.toml`` / ``requirements*.txt`` /
  工作流）—— 影响面不是依赖图说得清的；
* 一个测试都没选中 —— 没有测试依赖这些文件，L0 什么都证明不了。

缓存
====
每个文件抽出的原始引用按 (mtime, 大小) 增量缓存在 ``runtime/verification_ladder/``：
首次全量解析约 15 秒，之后不到半秒。缓存损坏或版本不符一律当作没有。
"""

from __future__ import annotations

import ast
import json
import logging
import re
import zlib
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("Galaxy.VerificationLadder")

REPO_ROOT = Path(__file__).resolve().parent.parent

VERIFICATION_LADDER_IS_AUTHORITY: str = (
    "VERIFICATION_LADDER::SELECT_BY_DEPENDENCY_NEVER_BY_GUESS: "
    "core/verification_ladder.py decides which tests a change can affect from a "
    "static dependency graph (module-level imports transitively, lazy imports one "
    "hop, importlib literals, test string references, conftest scope, file-name "
    "references).  It says so (escalate_reason) whenever its answer cannot be "
    "trusted, and L3 (full CI) always remains the gate to the main branch."
)

LEVELS: Tuple[str, ...] = ("L0", "L1", "L2", "L3")

#: 不扫描的目录（第三方 vendored 代码、运行时产物、依赖目录）。
EXCLUDED_DIRS: frozenset = frozenset(
    {".git", "external", "node_modules", "__pycache__", "runtime", ".venv", "venv", "build", "dist", ".mypy_cache"}
)

#: pytest.ini 的 testpaths —— 只有这些目录下的 ``test_*.py`` 算测试。
TEST_ROOTS: Tuple[str, ...] = (
    "tests",
    "nodes/Node_71_MultiDeviceCoordination/tests",
    "nodes/Node_122_Shell/tests",
)

#: 改了这些，影响面不是依赖图说得清的（只认仓库根目录下的这些文件）。
GLOBAL_CONFIG_FILES: frozenset = frozenset(
    {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "mypy.ini", ".flake8", "conftest.py"}
)
_GLOBAL_CONFIG_PREFIXES: Tuple[str, ...] = ("requirements", ".github/workflows/")

#: 与 CI 分片作业同一套标记：L0 选中的是 CI 会跑的那部分。
CI_MARKER_EXPRESSION: str = "not slow and not manual"

#: CI 分片数（.github/workflows/ci.yml 的 matrix）。
CI_SHARD_COUNT: int = 4

#: L1 跑的静态守卫门：纯 AST，不装依赖，秒级。
STATIC_GUARD_SCRIPTS: Tuple[str, ...] = (
    "scripts/check_verdict_independence.py",
    "scripts/check_semantic_anchoring.py",
    "scripts/check_import_boundaries.py --strict",
    "scripts/check_file_complexity.py --strict",
    "scripts/check_reachability.py",
    "scripts/check_wiring.py --strict",
    "scripts/check_evidence_anchors.py",
    "scripts/check_assessment_freshness.py",
)

INIT_SUFFIX = "#init"

_CACHE_VERSION = 4
_CACHE_PATH = REPO_ROOT / "runtime" / "verification_ladder" / "dependency_index.json"

_DOTTED_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_PATH_RE = re.compile(r"^[\w.\-/]+\.py$")
_DEFERRED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


# ---------------------------------------------------------------------------
# 文件全集与模块名
# ---------------------------------------------------------------------------


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _python_files(root: Path) -> List[Path]:
    out: List[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix == ".py":
                out.append(entry)
    return sorted(out)


def module_name_for(rel_path: str) -> str:
    """``core/meta/__init__.py`` → ``core.meta``；``core/x.py`` → ``core.x``。"""
    parts = rel_path[:-3].split("/") if rel_path.endswith(".py") else rel_path.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    if not (name.startswith("test_") and name.endswith(".py")):
        return False
    return any(rel_path.startswith(root + "/") for root in TEST_ROOTS)


def _is_test_context(rel_path: str) -> bool:
    return is_test_file(rel_path) or rel_path.endswith("/conftest.py")


def _init_node(package_file: str) -> str:
    """父包 ``__init__.py`` 的「只执行模块级代码」伪节点。非包文件原样返回。"""
    return package_file + INIT_SUFFIX if package_file.endswith("__init__.py") else package_file


# ---------------------------------------------------------------------------
# 单文件抽取（可缓存的原始事实）
# ---------------------------------------------------------------------------


def _extract(source: str, rel_path: str) -> Dict[str, List[Any]]:
    """抽出一个文件的原始引用。

    imports: ``[相对层级, 模块, [名字...], 是否模块级]``
    dynamic: ``import_module("x")`` / ``__import__("x")`` 的字面量 ``[名字, 是否模块级]``
    strings: 字符串常量里形如点号模块名或 ``.py`` 路径的（只对测试文件生效）
    """
    try:
        tree = ast.parse(source, filename=rel_path)
    except (SyntaxError, ValueError):
        return {"imports": [], "dynamic": [], "strings": []}
    imports: List[Any] = []
    dynamic: List[Any] = []
    strings: Set[str] = set()
    stack: List[Tuple[ast.AST, bool]] = [(tree, True)]
    while stack:
        node, toplevel = stack.pop()
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append([0, alias.name, [], toplevel])
        elif isinstance(node, ast.ImportFrom):
            imports.append([node.level or 0, node.module or "", [a.name for a in node.names], toplevel])
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if fname in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                dynamic.append([node.args[0].value.strip(), toplevel])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if 3 <= len(value) <= 200 and (_DOTTED_RE.match(value) or _PATH_RE.match(value)):
                strings.add(value)
        child_top = toplevel and not isinstance(node, _DEFERRED_SCOPES)
        stack.extend((child, child_top) for child in ast.iter_child_nodes(node))
    return {"imports": imports, "dynamic": dynamic, "strings": sorted(strings)}


# ---------------------------------------------------------------------------
# 依赖图
# ---------------------------------------------------------------------------


@dataclass
class DependencyIndex:
    """仓库的静态依赖图。

    * ``top_dependents[x]`` —— 在**模块级**依赖 x 的节点（反向边，用于无限传递）；
    * ``lazy_deps[f]``      —— f 函数体里懒导入的节点（正向边，只走一跳）；
    * ``direct_deps[f]``    —— f 的全部直接依赖（测试 / conftest 用）。
    节点是文件路径，或包的 ``__init__.py#init`` 伪节点。
    """

    files: List[str]
    modules: Dict[str, str]
    top_dependents: Dict[str, Set[str]]
    lazy_deps: Dict[str, Set[str]]
    direct_deps: Dict[str, Set[str]]

    @property
    def test_files(self) -> List[str]:
        return [f for f in self.files if is_test_file(f)]


def _load_cache() -> Dict[str, Any]:
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != _CACHE_VERSION:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _save_cache(entries: Dict[str, Any]) -> None:
    try:
        from core.atomic_json import atomic_write_json

        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_CACHE_PATH, {"version": _CACHE_VERSION, "entries": entries})
    except Exception as exc:  # noqa: BLE001 — 缓存只是加速，写不下就下次重算
        logger.debug("依赖图缓存写入跳过：%s", exc)


def _resolve_import(importer: str, level: int, module: str, names: Sequence[str], modules: Dict[str, str]) -> Set[str]:
    """把一条 import 解析成被依赖的节点集合。

    * 真正被使用的模块 → 文件节点；
    * 只是被隐式执行的父包 → ``#init`` 伪节点。
    """
    if level:
        package_parts = module_name_for(importer).split(".")
        if not importer.endswith("__init__.py"):
            package_parts = package_parts[:-1]
        base_parts = package_parts[: len(package_parts) - (level - 1)] if level > 1 else package_parts
        base = ".".join(p for p in base_parts if p)
        module = f"{base}.{module}" if module and base else (module or base)
    if not module:
        return set()
    targets: Set[str] = set()
    parts = module.split(".")
    for i in range(1, len(parts)):
        hit = modules.get(".".join(parts[:i]))
        if hit:
            targets.add(_init_node(hit))
    base_hit = modules.get(module)
    uses_package_itself = not names
    for name in names:
        sub = modules.get(f"{module}.{name}") if name != "*" else None
        if sub:
            targets.add(sub)
        else:
            uses_package_itself = True
    if base_hit:
        targets.add(base_hit if uses_package_itself else _init_node(base_hit))
    return targets


def _resolve_string(value: str, modules: Dict[str, str], files: Set[str]) -> Set[str]:
    if value.endswith(".py"):
        normalized = value[2:] if value.startswith("./") else value
        return {normalized} if normalized in files else set()
    parts = value.split(".")
    for i in range(len(parts), 1, -1):
        hit = modules.get(".".join(parts[:i]))
        if hit:
            return {hit} | {
                _init_node(modules[".".join(parts[:j])]) for j in range(1, i) if ".".join(parts[:j]) in modules
            }
    return set()


def _scan_entries(use_cache: bool) -> Dict[str, Any]:
    paths = _python_files(REPO_ROOT)
    cached = _load_cache() if use_cache else {}
    entries: Dict[str, Any] = {}
    dirty = False
    for path in paths:
        rel = _rel(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        stamp = [stat.st_mtime_ns, stat.st_size]
        hit = cached.get(rel)
        if isinstance(hit, dict) and hit.get("stamp") == stamp:
            entries[rel] = hit
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entries[rel] = {"stamp": stamp, **_extract(source, rel)}
        dirty = True
    if use_cache and (dirty or set(entries) != set(cached)):
        _save_cache(entries)
    return entries


def build_dependency_index(use_cache: bool = True) -> DependencyIndex:
    """构建（或增量刷新）仓库依赖图。"""
    entries = _scan_entries(use_cache)
    files = sorted(entries)
    file_set = set(files)
    modules = {module_name_for(f): f for f in files}
    top_dependents: Dict[str, Set[str]] = {}
    lazy_deps: Dict[str, Set[str]] = {}
    direct_deps: Dict[str, Set[str]] = {}

    def _add_top(user: str, targets: Set[str]) -> None:
        for target in targets - {user}:
            top_dependents.setdefault(target, set()).add(user)

    for rel, entry in entries.items():
        top: Set[str] = set()
        lazy: Set[str] = set()
        for item in entry.get("imports", []):
            resolved = _resolve_import(rel, int(item[0]), str(item[1]), list(item[2]), modules)
            (top if item[3] else lazy).update(resolved)
        for name, toplevel in entry.get("dynamic", []):
            (top if toplevel else lazy).update(_resolve_string(str(name), modules, file_set))
        refs: Set[str] = set()
        if _is_test_context(rel):
            for value in entry.get("strings", []):
                refs |= _resolve_string(value, modules, file_set)

        # 文件节点：模块级依赖无限传递；包的文件节点还依赖它自己的 #init。
        _add_top(rel, top)
        if rel.endswith("__init__.py"):
            _add_top(rel + INIT_SUFFIX, top)
            top_dependents.setdefault(rel + INIT_SUFFIX, set()).add(rel)
        lazy_deps[rel] = lazy - {rel}
        direct_deps[rel] = (top | lazy | refs) - {rel}
    return DependencyIndex(
        files=files, modules=modules, top_dependents=top_dependents, lazy_deps=lazy_deps, direct_deps=direct_deps
    )


# ---------------------------------------------------------------------------
# 选择
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LadderPlan:
    """一次改动在四档上分别要跑什么。"""

    changed: Tuple[str, ...]
    tests: Tuple[str, ...]
    shards: Tuple[int, ...]
    escalate_reason: str = ""
    affected_sources: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def l0_trustworthy(self) -> bool:
        return not self.escalate_reason

    def commands(self, level: str) -> List[str]:
        """这一档要跑的验证命令（均为 core.engineering_verification 认得的验证器）。

        L3 是全量 CI，本地没有一条等价的命令，返回空列表 —— 调用方据此知道这一档只能交给 CI。
        """
        if level not in LEVELS:
            raise ValueError(f"未知档位 {level!r}，可选 {LEVELS}")
        l0 = [pytest_command(self.tests)] if self.tests else []
        if level == "L0":
            return l0
        guards = [f"python {g}" for g in STATIC_GUARD_SCRIPTS]
        if level == "L1":
            return l0 + guards
        if level == "L2":
            return guards + [pytest_command(("tests/",))]
        return []

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["l0_trustworthy"] = self.l0_trustworthy
        data["commands"] = {level: self.commands(level) for level in LEVELS}
        return data


def pytest_command(targets: Sequence[str]) -> str:
    """L0 / L2 用的 pytest 命令：与 CI 分片同一套标记。"""
    return f'pytest {" ".join(targets)} -q -m "{CI_MARKER_EXPRESSION}" -p no:cacheprovider'


def _normalize_changed(paths: Iterable[str]) -> List[str]:
    out: List[str] = []
    for raw in paths:
        text = str(raw).strip()
        if not text:
            continue
        candidate = Path(text)
        if candidate.is_absolute():
            try:
                text = candidate.resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                continue
        text = text.replace("\\", "/")
        out.append(text[2:] if text.startswith("./") else text)
    return sorted(set(out))


def _is_global_config(rel: str) -> bool:
    if "/" not in rel and rel in GLOBAL_CONFIG_FILES:
        return True
    return rel.startswith(_GLOBAL_CONFIG_PREFIXES)


def _readers_of_non_python(rel: str, index: DependencyIndex) -> Set[str]:
    """源码里出现这个文件名的 .py —— 读它的人。"""
    name = rel.rsplit("/", 1)[-1]
    readers: Set[str] = set()
    if not name:
        return readers
    for candidate in index.files:
        try:
            if name in (REPO_ROOT / candidate).read_text(encoding="utf-8", errors="replace"):
                readers.add(candidate)
        except OSError:
            continue
    return readers


def _shard_of(test_file: str, total: int = CI_SHARD_COUNT) -> int:
    """与 scripts/ci_test_shard.py 同一算法：按路径 crc32 分配，1-based。"""
    return zlib.crc32(test_file.encode("utf-8")) % total + 1


def _top_level_reverse_closure(seeds: Set[str], index: DependencyIndex) -> Set[str]:
    reached = set(seeds)
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        for dependent in index.top_dependents.get(current, ()):
            if dependent not in reached:
                reached.add(dependent)
                queue.append(dependent)
    return reached


def select_affected_tests(changed_paths: Iterable[str], index: Optional[DependencyIndex] = None) -> LadderPlan:
    """给定改动的文件，算出 L0 要跑的测试，以及 L0 的结论是否可信。"""
    changed = _normalize_changed(changed_paths)
    index = index or build_dependency_index()
    file_set = set(index.files)

    reasons: List[str] = []
    global_hits = [c for c in changed if _is_global_config(c)]
    if global_hits:
        reasons.append(f"改了全局配置 {global_hits}，影响面不是依赖图说得清的")

    seeds: Set[str] = set()
    for rel in changed:
        if rel in file_set:
            seeds.add(rel)
        elif not rel.endswith(".py"):
            seeds |= _readers_of_non_python(rel, index)
    seeds |= {_init_node(s) for s in seeds}

    # R：模块级导入时就会把改动执行到的节点（无限传递）。
    reached = _top_level_reverse_closure(seeds, index)
    # R1：再加上「函数体里懒导入命中 R」的模块 —— 懒导入只算一跳。
    reached_one_lazy_hop = reached | {f for f, lazy in index.lazy_deps.items() if lazy & reached}

    def _affected(user: str) -> bool:
        return user in reached or bool(index.direct_deps.get(user, set()) & reached_one_lazy_hop)

    affected_tests = {t for t in index.test_files if _affected(t)}
    for conftest in (f for f in index.files if f.endswith("/conftest.py") and _affected(f)):
        scope = conftest[: -len("conftest.py")]
        affected_tests |= {t for t in index.test_files if t.startswith(scope)}

    tests = sorted(affected_tests)
    if not tests and not reasons:
        reasons.append("没有任何测试依赖这些文件 —— L0 什么都证明不了")

    return LadderPlan(
        changed=tuple(changed),
        tests=tuple(tests),
        shards=tuple(sorted({_shard_of(t) for t in tests})),
        escalate_reason="；".join(reasons),
        affected_sources=tuple(sorted(f for f in reached_one_lazy_hop if f in file_set and not is_test_file(f))),
    )


def recommended_level(plan: LadderPlan) -> str:
    """L0 可信就从 L0 起；不可信直接上 L2（test:fast 全量）。L3 只在合入主干时由 CI 跑。"""
    return "L0" if plan.l0_trustworthy else "L2"


__all__ = [
    "CI_MARKER_EXPRESSION",
    "LEVELS",
    "STATIC_GUARD_SCRIPTS",
    "VERIFICATION_LADDER_IS_AUTHORITY",
    "DependencyIndex",
    "LadderPlan",
    "build_dependency_index",
    "is_test_file",
    "module_name_for",
    "pytest_command",
    "recommended_level",
    "select_affected_tests",
]
