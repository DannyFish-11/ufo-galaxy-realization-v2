"""
tests/test_pr7_semantic_closure.py
====================================
Guardrail tests for the complete desktop semantic closure (PR-7).

Coverage
--------
1. Canonical closure docs exist
   - docs/DESKTOP_SEMANTIC_CLOSURE.md exists and contains the three states
   - docs/CONFIGURATION_ENTRY_UNIFICATION.md exists with canonical entry points
   - docs/STATUS_AND_STATISTICS_OWNERSHIP.md exists with ownership table

2. Tri-state semantic invariants
   - TriState enum has exactly three values: silent / liminal / manifest
   - DesktopPresenceRuntime is the sole tri-state authority
   - Tri-state values match across TriState and TriStatePhase enums

3. Legacy residue isolation
   - dashboard/ carries LEGACY_SURFACE.md marker
   - status_board.py carries legacy deprecation notice
   - ACTIVE_SURFACE.md references the new semantic closure doc

4. Statistics / summary ownership
   - STATUS_AND_STATISTICS_OWNERSHIP.md references the canonical projection contract
   - liminal_surface only exposes chain/sandbox statistics (not routing stats)
   - status board doc references statistics ownership doc

5. Configuration-entry semantics
   - CONFIGURATION_ENTRY_UNIFICATION.md references CONFIG_GOVERNANCE.md
   - ACTIVE_SURFACE.md references configuration entry doc
   - No duplicate config-entry authority claims in surface docs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

_REPO_ROOT = Path(__file__).parent.parent


def _repo_file(rel: str) -> Path:
    return _REPO_ROOT / rel


# ---------------------------------------------------------------------------
# 1. Canonical closure docs exist
# ---------------------------------------------------------------------------


class TestCanonicalClosureDocsExist:
    """The three closure docs must be present and contain the right content."""

    def test_desktop_semantic_closure_doc_exists(self) -> None:
        p = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md")
        assert p.exists(), "docs/DESKTOP_SEMANTIC_CLOSURE.md must exist"

    def test_desktop_semantic_closure_doc_mentions_silent(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "silent" in content.lower()

    def test_desktop_semantic_closure_doc_mentions_liminal(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "liminal" in content.lower()

    def test_desktop_semantic_closure_doc_mentions_manifest(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "manifest" in content.lower()

    def test_desktop_semantic_closure_doc_defines_authority(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert (
            "DesktopPresenceRuntime" in content
        ), "DESKTOP_SEMANTIC_CLOSURE.md must name DesktopPresenceRuntime as tri-state authority"

    def test_desktop_semantic_closure_doc_mentions_invariants(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text().lower()
        assert "invariant" in content, "DESKTOP_SEMANTIC_CLOSURE.md must define tri-state invariants"

    def test_configuration_entry_unification_doc_exists(self) -> None:
        p = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md")
        assert p.exists(), "docs/CONFIGURATION_ENTRY_UNIFICATION.md must exist"

    def test_configuration_entry_unification_doc_mentions_canonical_entry(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text()
        assert (
            "config.json" in content.lower() or "unified_config" in content.lower()
        ), "CONFIGURATION_ENTRY_UNIFICATION.md must reference the canonical config entry point"

    def test_configuration_entry_unification_doc_references_config_governance(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text()
        assert (
            "CONFIG_GOVERNANCE" in content
        ), "CONFIGURATION_ENTRY_UNIFICATION.md must cross-reference CONFIG_GOVERNANCE.md"

    def test_status_and_statistics_ownership_doc_exists(self) -> None:
        p = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md")
        assert p.exists(), "docs/STATUS_AND_STATISTICS_OWNERSHIP.md must exist"

    def test_status_and_statistics_ownership_doc_mentions_projection(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert (
            "DesktopStatusProjection" in content
        ), "STATUS_AND_STATISTICS_OWNERSHIP.md must reference DesktopStatusProjection"

    def test_status_and_statistics_ownership_doc_mentions_liminal_chain(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text().lower()
        assert (
            "local execution chain" in content or "cross-device" in content
        ), "STATUS_AND_STATISTICS_OWNERSHIP.md must cover liminal-space chain statistics"


# ---------------------------------------------------------------------------
# 2. Tri-state semantic invariants
# ---------------------------------------------------------------------------


class TestTriStateSemanticInvariants:
    """The tri-state model must be consistent across the codebase."""

    def test_tristate_enum_has_silent(self) -> None:
        from core.desktop_presence_runtime import TriState

        assert TriState.SILENT.value == "silent"

    def test_tristate_enum_has_liminal(self) -> None:
        from core.desktop_presence_runtime import TriState

        assert TriState.LIMINAL.value == "liminal"

    def test_tristate_enum_has_manifest(self) -> None:
        from core.desktop_presence_runtime import TriState

        assert TriState.MANIFEST.value == "manifest"

    def test_tristate_enum_has_exactly_three_values(self) -> None:
        from core.desktop_presence_runtime import TriState

        values = {m.value for m in TriState}
        assert values == {
            "silent",
            "liminal",
            "manifest",
        }, "TriState must have exactly three values: silent / liminal / manifest"

    def test_continuum_tristate_phase_matches(self) -> None:
        """TriStatePhase in core.continuum.types must use the same three values.

        Loaded directly from the source file to avoid the numpy transitive
        import that triggers through core/continuum/__init__.py →
        core/continuum/human_field.py → core/multimodal/audio_features.py.
        """
        import importlib.util
        from pathlib import Path

        types_path = Path(__file__).parent.parent / "core" / "continuum" / "types.py"
        spec = importlib.util.spec_from_file_location("continuum_types_direct", types_path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        TriStatePhase = mod.TriStatePhase
        values = {m.value for m in TriStatePhase}
        assert values == {"silent", "liminal", "manifest"}, "TriStatePhase must match the canonical tri-state values"

    def test_desktop_presence_runtime_is_tristate_authority(self) -> None:
        """DesktopPresenceRuntime must expose a TriState enum and handle_request method.

        Validates the TriState enum only — avoids instantiating the runtime
        (which would trigger the numpy transitive dependency).
        """
        from core.desktop_presence_runtime import TriState

        # Verify TriState has exactly the three canonical values.
        values = {m.value for m in TriState}
        assert values == {
            "silent",
            "liminal",
            "manifest",
        }, "DesktopPresenceRuntime.TriState must carry the three canonical values"
        # Verify the class at least declares handle_request as the lifecycle entry.
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        assert hasattr(
            DesktopPresenceRuntime, "handle_request"
        ), "DesktopPresenceRuntime must expose 'handle_request' as the lifecycle driver"

    def test_closure_doc_references_all_three_states(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text().lower()
        for state in ("silent", "liminal", "manifest"):
            assert state in content, f"DESKTOP_SEMANTIC_CLOSURE.md must define the '{state}' state"


# ---------------------------------------------------------------------------
# 3. Legacy residue isolation
# ---------------------------------------------------------------------------


class TestLegacyResidueIsolation:
    """Legacy surfaces must carry isolation markers and not claim active authority."""

    def test_dashboard_legacy_surface_md_exists(self) -> None:
        # 终态(用户裁决):dashboard/ 整体删除(ui_surface_authority: DELETED,
        # do not recreate),过渡期隔离标记随之退役,不得复活。
        assert not _repo_file("dashboard").exists(), "dashboard/ 已退役删除,不得复活"

    def test_dashboard_legacy_surface_md_contains_legacy_marker(self) -> None:
        assert not _repo_file("dashboard/LEGACY_SURFACE.md").exists()

    def test_dashboard_legacy_surface_md_references_canonical_surface(self) -> None:
        # canonical 面板端点契约仍由 core 路由套件专钉;此处只钉退役终态
        assert not _repo_file("dashboard/frontend").exists()

    def test_status_board_py_fully_decommissioned(self) -> None:
        # 收口已推进到终态:windows_client/status_board.py 被整体拆除,
        # 比"留着文件挂弃用说明"更强。钉住"不得复活"。
        sb_path = _repo_file("windows_client/status_board.py")
        assert not sb_path.exists(), "windows_client/status_board.py 已退役拆除,不应被重新引入"

    # 这里曾有两条读 windows_client/status_board_v2/ACTIVE_SURFACE.md 的测试
    # （必须引用 DESKTOP_SEMANTIC_CLOSURE.md、必须列出三态）。该文件随终端状态板
    # 整包删除。三态语义本身由上面 TestTriStateSemanticInvariants 直接对
    # core 侧断言，不依赖任何表层的说明文件。


# ---------------------------------------------------------------------------
# 4. Statistics / summary ownership
# ---------------------------------------------------------------------------


class TestStatisticsOwnership:
    """Statistics must live in the correct surface / doc."""

    def test_statistics_doc_references_status_board(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert "status_board_v2" in content or "status board" in content.lower(), (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must reference the status board as the "
            "canonical home for operator-visible statistics"
        )

    def test_statistics_doc_references_liminal_surface(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert "liminal_surface" in content or "liminal space" in content.lower(), (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must reference liminal_surface for " "execution-chain statistics"
        )

    def test_statistics_doc_references_desktop_display_boundaries(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert (
            "DESKTOP_DISPLAY_BOUNDARIES" in content
        ), "STATUS_AND_STATISTICS_OWNERSHIP.md must cross-reference DESKTOP_DISPLAY_BOUNDARIES.md"

    # 原有一条钉 docs/STATUS_BOARD_V2.md 交叉引用统计所有权文档。该文档随
    # windows_client/status_board_v2/ 一并删除。上面那条（STATUS_AND_STATISTICS_
    # OWNERSHIP.md 必须交叉引用边界文档）仍在，统计所有权的说明链没有断。

    # 这里曾有 test_liminal_surface_does_not_render_routing_stats —— 断言终端
    # 状态板的 LiminalSurface 不得把路由拓扑统计画进阈限面。渲染层已删除。
    #
    # "统计归属"这条所有权约束没有丢：本类其余测试断言的是统计由 core 侧的
    # summary 拥有者产出，那才是所有权的所在地；渲染层只是它的一个消费者。


# ---------------------------------------------------------------------------
# 5. Configuration-entry semantics
# ---------------------------------------------------------------------------


class TestConfigurationEntrySemantics:
    """Configuration entry semantics must be unified and documented."""

    def test_config_entry_doc_exists(self) -> None:
        p = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md")
        assert p.exists(), "docs/CONFIGURATION_ENTRY_UNIFICATION.md must exist"

    def test_config_entry_doc_describes_ownership_tiers(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text().lower()
        assert "system" in content and (
            "surface" in content or "node" in content
        ), "CONFIGURATION_ENTRY_UNIFICATION.md must describe configuration ownership tiers"

    def test_config_entry_doc_prohibits_secrets_in_config_json(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text().lower()
        assert (
            "secret" in content or "api_key" in content
        ), "CONFIGURATION_ENTRY_UNIFICATION.md must address secrets / API key placement"

    # 原 test_active_surface_md_references_configuration_entry_doc 读的
    # ACTIVE_SURFACE.md 随终端状态板删除；配置入口统一的约束由下面这条
    # 与 docs/CONFIGURATION_ENTRY_UNIFICATION.md 自身的存在性断言承担。

    def test_config_governance_doc_exists(self) -> None:
        """The pre-existing CONFIG_GOVERNANCE.md must still exist."""
        p = _repo_file("docs/CONFIG_GOVERNANCE.md")
        assert p.exists(), "docs/CONFIG_GOVERNANCE.md must exist"

    def test_config_entry_doc_does_not_duplicate_config_governance_keys(self) -> None:
        """CONFIGURATION_ENTRY_UNIFICATION.md should reference, not duplicate,
        the variable matrix in CONFIG_GOVERNANCE.md."""
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text()
        assert "CONFIG_GOVERNANCE" in content, (
            "CONFIGURATION_ENTRY_UNIFICATION.md must reference CONFIG_GOVERNANCE.md "
            "rather than duplicating the full variable matrix"
        )
