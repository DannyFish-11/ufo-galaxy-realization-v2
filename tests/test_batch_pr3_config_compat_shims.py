#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_batch_pr3_config_compat_shims.py
============================================

Batch PR-3 — Unify configuration authority, eliminate forbidden fallbacks,
and standardize compatibility shims.

Coverage areas
--------------
A) launcher/config_manager: 已按其登记的退役条件物理删除；本组钉的是退役终态
   （不复活、无 importer 回流、替代品在位），不再钉 DeprecationWarning。
B) dashboard/backend/main.py: forbidden inline UnifiedChatResponse fallback
   class is gone; the import is now a hard dependency.
C) dashboard/backend/main.py: get_cors_origins uses _AVAILABLE flag pattern,
   no inline function definition in the except block.
D) dashboard/backend/main.py: ascii_art uses _AVAILABLE flag pattern.
E) core/routes/compat.py: deprecation metadata present in docstring;
   create_router() emits DeprecationWarning.
   (``.. deprecated::`` annotation and removal target) present.
G) core/legacy_adapters/device_agent_manager_adapter.py: deprecation metadata
   present.
H) galaxy_gateway/legacy/capability_registry.py: DeprecationWarning emitted
   at import time; deprecation metadata in docstring.
I) galaxy_gateway/legacy/task_decomposer.py: DeprecationWarning emitted at
   import time; deprecation metadata in docstring.
J) docs/CONFIGURATION_AUTHORITY.md: config.json reclassification is documented,
   and launcher/config_manager.py's section states its RETIRED terminal state
   plus the replacement paths (section-scoped, not file-wide keyword match).
K) docs/migration/LEGACY_SURFACE_INVENTORY.md: launcher/config_manager.py
   still listed (retirement is recorded, not erased) and marked RETIRED in
   agreement with core/compat_surface_retirement.py; shims carry PR-3 column.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

# sys / textwrap / types / warnings / pytest 全部删掉：它们是"用 importlib 造一个
# 假模块、再 catch_warnings 捕 DeprecationWarning"那套动态检查留下的。检查对象
# （launcher/config_manager.py）退役后那套没了，本文件现在只做静态与 AST 判定。

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _has_deprecated_docstring(source: str) -> bool:
    """Return True if the module docstring contains '.. deprecated::'."""
    return ".. deprecated::" in source


def _has_removal_target(source: str) -> bool:
    """Return True if the source mentions a removal target (Batch PR-N)."""
    return "Removal target" in source or "removal target" in source


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str:
    """把一条 ``from ... import`` 还原成**绝对**模块名。

    ``node.level`` 是相对层级：0 = 绝对导入，1 = ``from .x``，2 = ``from ..x``。
    相对导入的基准是**所在包**，所以先由文件路径推出包路径，再上溯 level-1 层。

    存在这个函数，是因为只看 ``node.module`` 会把 ``from .config_manager``
    读成 ``"config_manager"``，与顶层同名模块混为一谈 —— 而这正是相对 import
    能从子串扫描器底下溜走的原因。
    """
    if node.level == 0:
        return node.module or ""
    pkg_parts = list(path.relative_to(REPO_ROOT).parts[:-1])
    # level=1 指当前包；每多一级向上退一层包
    up = node.level - 1
    if up:
        pkg_parts = pkg_parts[:-up] if up <= len(pkg_parts) else []
    return ".".join(pkg_parts + ([node.module] if node.module else []))


# ---------------------------------------------------------------------------
# A) launcher/config_manager — RETIRED (physically deleted); terminal-state pins
# ---------------------------------------------------------------------------


class TestLauncherConfigManagerRetired:
    """终态：``launcher/config_manager.py`` 已按其自身登记的退役条件物理删除。

    ``core/compat_surface_retirement.py`` 里那条记录写的条件是：

        Remove when no caller outside of deprecation tests imports
        launcher.config_manager and port data consumers have been confirmed
        migrated to core.port_config.

    退役前逐条核过：``from launcher.config_manager import ...`` 的真 import
    在全仓为 **0**（其余同名命中都是各文件自己定义的 ``ConfigManager`` /
    ``NodeConfig``，同名不同源）；而端口消费方早已走 ``core.port_config``
    —— ``system_manager.ConfigManager._get_canonical_port`` 就是那条路。

    该模块自己的头部还写着"the hardcoded port defaults below are **STALE** and
    conflict with config/unified_ports.yaml"，留着它反而是一个会误导人的
    陈旧端口来源。

    原本这组测试钉的是"它必须仍然发 DeprecationWarning"。检查对象没了，
    收敛为退役终态钉 —— 与本文件里 dashboard 那组的处理方式一致。
    """

    def test_module_is_gone(self):
        assert not (
            REPO_ROOT / "launcher" / "config_manager.py"
        ).exists(), "launcher/config_manager.py 已退役删除，不得复活"

    def test_no_production_importer_reappeared(self):
        """防回归：不许有人把 import 加回来。

        **按 AST 判定，不按子串。** 第一版这条测试搜的是字面量
        ``"from launcher.config_manager import"``，两头都错：

        - 假阳性：本文件和 ``launcher/__init__.py`` 的**注释/文档**里出现这串字，
          就被当成 importer（扫描器读到自己写的字 —— 与 API 面扫描器读到自己
          生成的 ``api.gen.ts`` 是同一类自指陷阱）。
        - 假阴性（真放过了 bug）：``launcher/dependency_resolver.py`` 里写的是
          **相对** import ``from .config_manager import NodeConfig``，子串
          ``"launcher.config_manager"`` 永远匹配不到。删除后那个模块直接
          ``ModuleNotFoundError``，而这条测试是绿的。

        改成解析 AST 后，两类都消失：注释不进 AST；相对 import 由
        ``ImportFrom.level`` + 所在包路径还原成绝对模块名后一并判定。
        """
        offenders = []
        for path in REPO_ROOT.rglob("*.py"):
            # external/ 是 vendored 上游代码：它不可能 import 本仓的 launcher，
            # 扫它只会把上游自己的语法告警（如 invalid escape sequence）算到我们头上。
            if any(part in path.parts for part in ("__pycache__", ".venv", "venv", "node_modules", ".git", "external")):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (SyntaxError, ValueError, OSError):
                continue  # 非本测试职责（语法错误另有 lint 把关）
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(a.name == "launcher.config_manager" for a in node.names):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    if _resolve_import_from(path, node) == "launcher.config_manager":
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
        assert not offenders, f"launcher.config_manager 又被 import 了：{offenders}"

    def test_scanner_catches_relative_imports(self):
        """自证：上面那条扫描器确实能看见 ``from .config_manager import X``。

        没有这条，扫描器退回子串实现后照样全绿 —— 而它正是漏掉真 bug 的那版。
        """
        src = "from .config_manager import NodeConfig\n"
        node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom))
        fake = REPO_ROOT / "launcher" / "dependency_resolver.py"
        assert _resolve_import_from(fake, node) == "launcher.config_manager"

    def test_launcher_package_all_modules_import(self):
        """``launcher/`` 下每个模块都必须真能 import。

        这是本轮漏检的根因守卫：``dependency_resolver`` 断了整整一次提交，
        因为没有任何测试**执行**过它 —— 只有静态断言。
        """
        broken = []
        for path in sorted((REPO_ROOT / "launcher").glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                importlib.import_module(f"launcher.{path.stem}")
            except Exception as exc:  # noqa: BLE001 — 要的就是"任何原因导致 import 不了"
                broken.append(f"{path.name}: {type(exc).__name__}: {exc}")
        assert not broken, "launcher/ 下有模块 import 失败：\n" + "\n".join(broken)

    def test_canonical_replacement_still_exists(self):
        """自证：上面两条只有在替代品确实在位时才成立。

        没有它，把替代品也一起删掉的情况下这组测试照样全绿。
        """
        assert (REPO_ROOT / "core" / "unified" / "config_manager.py").is_file()
        assert (REPO_ROOT / "core" / "port_config.py").is_file()


# ---------------------------------------------------------------------------
# B) dashboard/backend/main.py — no forbidden inline UnifiedChatResponse class
# ---------------------------------------------------------------------------


class TestDashboardRetired:
    """终态(用户裁决):dashboard/ 整体删除(ui_surface_authority: DELETED,
    do not recreate)。原三组模式检查(禁止内联 fallback / CORS 旗标 /
    ASCII art 旗标)的检查对象不复存在,收敛为退役终态钉。"""

    def test_dashboard_backend_main_retired(self):
        assert not (
            REPO_ROOT / "dashboard" / "backend" / "main.py"
        ).exists(), "dashboard/backend/main.py 已随目录退役删除,不得复活"

    def test_dashboard_package_retired(self):
        assert not (REPO_ROOT / "dashboard").exists()


class TestCompatRouteDeprecation:

    def test_module_has_deprecated_docstring(self):
        src = _read("core/routes/compat.py")
        assert _has_deprecated_docstring(
            src
        ), "core/routes/compat.py docstring must contain '.. deprecated::' annotation"

    def test_module_has_removal_target(self):
        src = _read("core/routes/compat.py")
        assert _has_removal_target(src), "core/routes/compat.py must declare a removal target (Batch PR-5)"

    def test_module_mentions_canonical_replacement(self):
        src = _read("core/routes/compat.py")
        assert (
            "core.routes.devices" in src or "/api/v1/devices" in src
        ), "core/routes/compat.py must name the canonical replacement route"

    def test_module_states_new_code_must_not_depend(self):
        src = _read("core/routes/compat.py")
        assert (
            "New code must not" in src or "new code must not" in src or "must not depend" in src
        ), "core/routes/compat.py must state that new code must not depend on it"

    def test_create_router_emits_deprecation_warning(self):
        src = _read("core/routes/compat.py")
        assert "warnings.warn" in src, "core/routes/compat.py create_router() must emit a DeprecationWarning"
        assert "DeprecationWarning" in src, "core/routes/compat.py must use DeprecationWarning category"

    def test_module_imports_warnings(self):
        src = _read("core/routes/compat.py")
        assert "import warnings" in src, "core/routes/compat.py must import the warnings module"

    def test_removal_target_pr5(self):
        src = _read("core/routes/compat.py")
        assert "PR-5" in src or "Batch PR-5" in src, "core/routes/compat.py must mention the PR-5 removal target"


# ---------------------------------------------------------------------------
# G) core/legacy_adapters/device_agent_manager_adapter.py — metadata
# ---------------------------------------------------------------------------


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# ---------------------------------------------------------------------------
# H) galaxy_gateway/legacy/capability_registry.py — DeprecationWarning
# ---------------------------------------------------------------------------


class TestGatewayLegacyCapabilityRegistry:

    def test_has_deprecated_docstring(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert _has_deprecated_docstring(
            src
        ), "galaxy_gateway/legacy/capability_registry.py must have '.. deprecated::' in its docstring"

    def test_has_removal_target(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert _has_removal_target(src), "galaxy_gateway/legacy/capability_registry.py must declare a removal target"

    def test_emits_deprecation_warning(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert "warnings.warn" in src, "galaxy_gateway/legacy/capability_registry.py must call warnings.warn()"
        assert "DeprecationWarning" in src, "DeprecationWarning must be passed to warnings.warn()"

    def test_mentions_canonical_replacement(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert (
            "core.capability_bus" in src or "capability_bus" in src
        ), "galaxy_gateway/legacy/capability_registry.py must name the canonical replacement"

    def test_new_code_must_not_depend(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert (
            "New code must not" in src or "new code must not" in src or "must not depend" in src
        ), "galaxy_gateway/legacy/capability_registry.py must state that new code must not depend on it"

    def test_removal_target_pr5(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert (
            "PR-5" in src or "Batch PR-5" in src
        ), "galaxy_gateway/legacy/capability_registry.py must mention PR-5 removal target"


# ---------------------------------------------------------------------------
# I) galaxy_gateway/legacy/task_decomposer.py — DeprecationWarning
# ---------------------------------------------------------------------------


class TestGatewayLegacyTaskDecomposer:

    def test_has_deprecated_docstring(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert _has_deprecated_docstring(
            src
        ), "galaxy_gateway/legacy/task_decomposer.py must have '.. deprecated::' in its docstring"

    def test_has_removal_target(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert _has_removal_target(src), "galaxy_gateway/legacy/task_decomposer.py must declare a removal target"

    def test_emits_deprecation_warning(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert "warnings.warn" in src, "galaxy_gateway/legacy/task_decomposer.py must call warnings.warn()"
        assert "DeprecationWarning" in src, "DeprecationWarning must be passed to warnings.warn()"

    def test_mentions_canonical_replacement(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert (
            "orchestrator" in src
        ), "galaxy_gateway/legacy/task_decomposer.py must name the canonical replacement (orchestrator)"

    def test_new_code_must_not_depend(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert (
            "New code must not" in src or "new code must not" in src or "must not depend" in src
        ), "galaxy_gateway/legacy/task_decomposer.py must state that new code must not depend on it"

    def test_removal_target_pr5(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert (
            "PR-5" in src or "Batch PR-5" in src
        ), "galaxy_gateway/legacy/task_decomposer.py must mention PR-5 removal target"


# ---------------------------------------------------------------------------
# J) docs/CONFIGURATION_AUTHORITY.md — config.json reclassification
# ---------------------------------------------------------------------------


class TestConfigAuthorityDocs:

    def test_config_json_reclassified(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        # Must state config.json is non-authoritative or static defaults
        assert (
            "static" in src.lower() and "config.json" in src
        ), "docs/CONFIGURATION_AUTHORITY.md must reclassify config.json as static defaults"
        assert (
            "non-authoritative" in src.lower() or "lowest" in src.lower() or "lowest-priority" in src.lower()
        ), "docs/CONFIGURATION_AUTHORITY.md must state config.json is the lowest-priority source"

    def test_launcher_config_manager_documented_as_retired(self):
        """原断言是"文件里某处出现 D2/HARD_DEPRECATED/Deprecated"。

        两个问题：(1) 它现在已经退役删除，"deprecated" 是过期描述；(2) 那条断言
        **不定位到章节** —— 文档任意角落有个 "Deprecated" 就算过，哪怕
        config_manager 那一节被整段改错也照样绿。这里改成取它自己的章节来判。
        """
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        marker = "### `launcher/config_manager.py`"
        assert marker in src, "docs/CONFIGURATION_AUTHORITY.md 必须仍有 launcher/config_manager.py 的章节"
        section = src.split(marker, 1)[1].split("\n### ", 1)[0]
        assert "RETIRED" in section or "已退役" in section, "该章节必须写明它已退役删除，而不是仍在 deprecated 状态"
        # 退役章节必须给出替代路径，否则读者到这儿就断了
        assert "core.port_config" in section
        assert "core.unified.config_manager" in section

    def test_canonical_config_stack_described(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert (
            "core/config_store.py" in src or "config_store" in src
        ), "docs/CONFIGURATION_AUTHORITY.md must describe the canonical config stack"
        assert (
            "core/config_service.py" in src or "config_service" in src
        ), "docs/CONFIGURATION_AUTHORITY.md must describe the canonical config stack"

    def test_runtime_config_json_distinguished_from_root_config_json(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert "runtime/config.json" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must distinguish runtime/config.json "
            "(canonical) from config.json (root, static)"
        )

    def test_config_json_do_not_write_secrets(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert (
            "secrets" in src.lower() or "Do not write" in src or "must never" in src
        ), "docs/CONFIGURATION_AUTHORITY.md must warn against writing secrets to config.json"


# ---------------------------------------------------------------------------
# K) docs/migration/LEGACY_SURFACE_INVENTORY.md — launcher/config_manager listed
# ---------------------------------------------------------------------------


class TestLegacySurfaceInventoryUpdated:

    def test_launcher_config_manager_listed(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        assert "launcher/config_manager.py" in src, "LEGACY_SURFACE_INVENTORY.md must list launcher/config_manager.py"

    def test_launcher_config_manager_is_retired(self):
        """原断言钉的是"这一行必须写 D2"。它已走完退役、被物理删除，
        D2（HARD_DEPRECATED）现在是**过期的**描述 —— 清单必须跟着走到终态。

        这条测试仍然存在的价值不变：清单不许悄悄把这一行删掉当没发生过
        （见 ``test_launcher_config_manager_listed``），且状态必须与
        ``core/compat_surface_retirement.py`` 的登记一致。
        """
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        lines = [line for line in src.splitlines() if "launcher/config_manager.py" in line]
        assert lines, "launcher/config_manager.py must appear in a table row"
        assert any(
            "RETIRED" in line for line in lines
        ), "launcher/config_manager.py 在 LEGACY_SURFACE_INVENTORY.md 必须标为 RETIRED"

    def test_inventory_row_agrees_with_retirement_registry(self):
        """两处记录不许各说各话。

        清单是文档、登记表是代码，此前它们只靠人肉同步；这条把"文档说 RETIRED"
        与"登记表 status==RETIRED"绑在一起，改一处漏一处会当场变红。
        """
        from core.compat_surface_retirement import RetirementStatus, get_compat_surface_inventory

        record = next(r for r in get_compat_surface_inventory() if r.surface_id == "launcher_config_manager_legacy")
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        row = next(line for line in src.splitlines() if "launcher/config_manager.py" in line)
        assert (record.status == RetirementStatus.RETIRED) == (
            "RETIRED" in row
        ), f"清单行与退役登记表不一致：登记表 status={record.status.value}，清单行={row!r}"

    def test_shims_have_pr3_status_column(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        assert "PR-3 Status" in src, (
            "LEGACY_SURFACE_INVENTORY.md section 6 must have a PR-3 Status column "
            "showing which shims received deprecation metadata in this batch"
        )

    def test_compat_routes_pr3_status_marked(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        # core/routes/compat.py row should show PR-3 completion
        lines = [line for line in src.splitlines() if "core/routes/compat.py" in line]
        assert lines, "core/routes/compat.py must appear in LEGACY_SURFACE_INVENTORY.md"
        assert any(
            "PR-3" in line or "✅" in line for line in lines
        ), "core/routes/compat.py shim row must show PR-3 status completion"

    def test_dashboard_fallback_pr3_status_marked(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        lines = [line for line in src.splitlines() if "dashboard/backend/main.py" in line]
        assert lines, "dashboard/backend/main.py must appear in LEGACY_SURFACE_INVENTORY.md"
        # Should note that PR-3 fixed the forbidden fallback
        assert any(
            "PR-3" in line for line in lines
        ), "dashboard/backend/main.py row must show PR-3 status (forbidden fallback removed)"


# ---------------------------------------------------------------------------
# Additional structural checks
# ---------------------------------------------------------------------------


class TestStructuralInvariants:

    def test_check_debt_freeze_passes(self):
        """Run the debt-freeze guardrail and assert no new violations."""
        import subprocess

        result = subprocess.run(
            ["python", "scripts/check_debt_freeze.py"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"check_debt_freeze.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        # "✅ Debt-freeze check passed" means no new violations
        assert (
            "Debt-freeze check passed" in result.stdout
        ), f"check_debt_freeze.py did not report clean pass:\n{result.stdout}"

    def test_dashboard_main_does_not_define_class_in_except_importerror(self):
        # 检查对象已退役删除;结构不变量以"不复活"为终态
        assert not (REPO_ROOT / "dashboard").exists()

    def test_core_routes_compat_no_business_logic(self):
        """Shim must not contain complex business logic (just delegation)."""
        src = _read("core/routes/compat.py")
        # The file may contain delegation logic (acceptable) but must not import
        # other business-logic modules as first-class dependencies.
        # Basic sanity: ensure it's still a thin router wrapper, not a full module.
        assert len(src) < 15_000, "core/routes/compat.py has grown too large; shims must be thin delegation wrappers"

    def test_launcher_config_manager_retired_without_orphaning_callers(self):
        """检查对象已退役删除；结构不变量以"退役没留下断口"为终态。

        原断言是"它必须仍然导出 ConfigManager / NodeConfig 供向后兼容"。模块删
        掉后这条不再有对象可查，但它背后真正在意的东西仍然成立且更值得钉：
        **删除不能把别人的 import 悬空**。``dependency_resolver`` 当初就是从这里
        取 ``NodeConfig`` 的，退役时必须一起收口（它现在自带 ``NodeSpec`` 结构
        协议，不再依赖任何具体配置类）。
        """
        assert not (REPO_ROOT / "launcher" / "config_manager.py").exists()
        # 曾经的下游必须仍可 import —— 这才是"退役干净"的可执行判据
        importlib.import_module("launcher.dependency_resolver")
        src = _read("launcher/dependency_resolver.py")
        # 按 AST 判定：该文件的**文档**里正引用着这行历史 import 作为说明，
        # 子串断言会当场把注释误判成代码（本文件上面刚记过这个陷阱）。
        path = REPO_ROOT / "launcher" / "dependency_resolver.py"
        modules = {_resolve_import_from(path, n) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
        assert (
            "launcher.config_manager" not in modules
        ), "dependency_resolver 不得再依赖已退役的 launcher.config_manager"
        assert "class NodeSpec" in src, "dependency_resolver 必须自带节点结构协议"
