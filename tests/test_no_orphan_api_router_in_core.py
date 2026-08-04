"""tests/test_no_orphan_api_router_in_core.py
=============================================
守卫：``core/`` 下不允许存在**定义了 FastAPI 路由却从未被挂载**的模块。

修的是什么
----------
``core/api_loader.py``（401 行，声明 MCP 加载/卸载/调用 9 个端点）与
``core/api_market.py``（347 行，声明技能市场 4 个端点）各自在模块顶层写了
``router = APIRouter()`` 并挂满了 ``@router.post(...)``，但**全仓没有任何一处
``include_router()`` 引用它们**。也就是说这两批端点在运行时的路由树里根本不存在。

这不是"暂时没启用"那么无害 —— 文档把它们当成真实 API 在教用户用：

- ``AGENTS.md`` 列了 ``POST /api/v1/mcp/load`` 等三条；
- ``skills/README.md`` 给了一整节可复制的 ``curl`` 命令；
- ``docs/HICLAW_IMPROVEMENTS.md`` 写着"复用现有 MCP API"。

照着敲只会拿到 404。两个模块已删除、相关文档已更正，本文件负责**防止复发**。

守卫的判据
----------
只查一件**机器能判定**的事：某个 ``core/`` 模块在顶层创建了 ``APIRouter()``，
那么它必须**至少被另一个生产模块 import**。判不了的（端点语义对不对、该不该
暴露）不查 —— 硬做只会制造噪音。

> 判据是"有没有被 import"，而不是"有没有被 include_router"。第一版就是按后者
> 写的，结果 26 个 ``core/routes/*`` 全部误报：它们被 ``core/api_routes.py`` 以
> **别名**挂载（``config_route.router``、``governance_routes.create_router()``、
> ``_device_health_router`` …），按模块名去匹配 ``include_router(...)`` 的实参
> 根本对不上。而"被不被 import"恰好就是这个缺陷的真实判别式 ——
> ``api_loader`` / ``api_market`` 的 importer 数是 **0**，其余每一个都 ≥1。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 会去里面找"挂载痕迹"的目录。刻意包含 tests/ 之外的全部生产面。
_MOUNT_SEARCH_DIRS = (
    "core",
    "galaxy_gateway",
    "nodes",
    "contracts",
    "integration",
    "subsystems",
    # 启动器统一（docs/LAUNCHER_UNIFICATION_PLAN.md）之后，挂载点搬到了这里：
    # ``launcher/services.py`` 承接了原 ``unified_launcher.py`` 的
    # ``include_router()``，``launcher/nodes.py`` 承接了原 ``system_manager.py``。
    # 漏掉这一条的表现很隐蔽 —— 不是报"找不到目录"，而是**误报孤儿路由**：
    # ``core/health_check.py`` 明明被挂着，却因为挂它的文件不在搜索面里而判成
    # 无人引用。
    "launcher",
)
# 仓库根上的入口文件。四个旧启动器本体（unified_launcher.py / system_manager.py /
# launch_desktop.py / install.py）已随统一删除，只剩 main.py 一个入口。
_MOUNT_SEARCH_FILES = ("main.py",)

_ROUTER_DEF = re.compile(r"^\s*(\w+)\s*=\s*APIRouter\s*\(", re.MULTILINE)
# 只看 import 行，避免把散文/注释里出现的模块名当成引用。
_IMPORT_LINE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\s+.+|import\s+[\w.,\s]+)$", re.MULTILINE)


def _iter_core_modules() -> List[Path]:
    out: List[Path] = []
    for p in (PROJECT_ROOT / "core").rglob("*.py"):
        if "__pycache__" in p.parts or p.name == "__init__.py":
            continue
        out.append(p)
    return out


def _production_sources() -> List[Tuple[str, str]]:
    """[(相对路径, 源码)]：所有生产面 Python 源码（读一次，全体用例共用）。"""
    out: List[Tuple[str, str]] = []
    for d in _MOUNT_SEARCH_DIRS:
        base = PROJECT_ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                out.append((str(p.relative_to(PROJECT_ROOT)), p.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    for f in _MOUNT_SEARCH_FILES:
        p = PROJECT_ROOT / f
        if p.is_file():
            out.append((f, p.read_text(encoding="utf-8", errors="ignore")))
    return out


_SOURCES = _production_sources()
_CORPUS = "\n".join(src for _, src in _SOURCES)
# 每个文件的 import 行单独存 —— 判"有没有被 import"时不该被散文/注释干扰，
# 而按文件分开存是为了能排除"自己 import 自己"这种情况而**不必**每次重拼语料
# （第一版就是每个候选重拼一次全仓 import 语料，7 条用例跑了 27s）。
_IMPORTS_BY_FILE = {rel: "\n".join(_IMPORT_LINE.findall(src)) for rel, src in _SOURCES}


def _find_orphans() -> List[Tuple[str, str]]:
    """返回 [(相对路径, 变量名)]：定义了 APIRouter 却没有任何生产模块 import 它。"""
    orphans: List[Tuple[str, str]] = []
    for path in _iter_core_modules():
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        defs = _ROUTER_DEF.findall(src)
        if not defs:
            continue

        rel = str(path.relative_to(PROJECT_ROOT))
        stem = path.stem
        word = re.compile(rf"\b{re.escape(stem)}\b")
        imported_by_someone_else = any(
            r != rel and stem in imports and word.search(imports) for r, imports in _IMPORTS_BY_FILE.items()
        )
        if imported_by_someone_else:
            continue
        orphans.append((rel, defs[0]))
    return orphans


class TestNoOrphanApiRouter:
    def test_no_core_module_defines_an_unmounted_router(self) -> None:
        orphans = _find_orphans()
        assert not orphans, (
            "以下 core/ 模块定义了 FastAPI 路由却没有任何 include_router() 把它挂上去 ——\n"
            "这些端点在运行时的路由树里不存在，但很容易被文档当成真实 API 写出去\n"
            "（core/api_loader.py 与 core/api_market.py 就是这样活了很久，直到被删）。\n"
            "要么在 core/api_routes.py 里挂上它，要么删掉这个模块：\n"
            + "\n".join(f"  - {p} （router 变量：{v}）" for p, v in orphans)
        )

    def test_the_two_known_offenders_are_gone(self) -> None:
        """回归钉子：这两个文件不该再回来。"""
        for name in ("core/api_loader.py", "core/api_market.py"):
            assert not (PROJECT_ROOT / name).exists(), f"{name} 是未挂载的孤儿路由，已删除，不应重新出现"

    def test_guard_actually_detects_an_orphan(self) -> None:
        """守卫本身要能抓到东西 —— 否则它绿得毫无意义。

        用一个临时的孤儿模块反向验证：判据能命中，不是恒真。
        """
        probe = PROJECT_ROOT / "core" / "_orphan_router_guard_probe.py"
        probe.write_text(
            "from fastapi import APIRouter\n\nrouter = APIRouter()\n",
            encoding="utf-8",
        )
        try:
            found = [p for p, _ in _find_orphans()]
            assert "core/_orphan_router_guard_probe.py" in found, "守卫判据失效：造出来的孤儿路由没被抓到"
        finally:
            probe.unlink(missing_ok=True)


class TestDeletedModulesLeaveNoDanglingImports:
    """删掉的四个模块不能在生产代码里留下悬空 import。"""

    @pytest.mark.parametrize(
        "module",
        ["api_loader", "api_market", "agent_context", "context_compressor"],
    )
    def test_no_production_import_of_deleted_module(self, module: str) -> None:
        pattern = re.compile(rf"(from\s+core\.{module}\s+import|import\s+core\.{module}\b)")
        hits = [m for m in pattern.finditer(_CORPUS)]
        assert not hits, f"core.{module} 已删除，但生产代码里仍有 import"
