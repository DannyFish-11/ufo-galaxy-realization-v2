#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PR-01: entrypoint role boundary hardening tests.
"""

from __future__ import annotations

from pathlib import Path

from entrypoint_role_contract import (
    ANDROID_V2_MAINLINE_BRIDGE_ANCHORS,
    ENTRYPOINT_ROLE_CONTRACT_SENTINEL,
    ENTRYPOINT_ROLE_REGISTRY,
    LEGACY_DOCKER_LAUNCHER_ENTRY_ID,
    LEGACY_WINDOWS_RUN_UI_ENTRY_ID,
    MAIN_ENTRY_ID,
    PRIMARY_STARTUP_CHAIN,
    UNIFIED_LAUNCHER_ENTRY_ID,
    EntrypointRole,
    assert_single_unique_main_entrypoint,
    build_entrypoint_role_snapshot,
    ensure_entrypoint_role,
)

REPO_ROOT = Path(__file__).parent.parent


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_contract_sentinel_present():
    assert ENTRYPOINT_ROLE_CONTRACT_SENTINEL.startswith("ENTRYPOINT_ROLE_CONTRACT_SENTINEL::PR01::")


def test_single_unique_main_entrypoint_is_main_py():
    assert assert_single_unique_main_entrypoint()
    assert ensure_entrypoint_role(MAIN_ENTRY_ID, EntrypointRole.UNIQUE_MAIN)


def test_primary_startup_chain_is_stable():
    assert PRIMARY_STARTUP_CHAIN == (
        MAIN_ENTRY_ID,
        UNIFIED_LAUNCHER_ENTRY_ID,
        "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        "core.openclawd:OpenClawd.process",
        "core.command_router:CommandRouter.route_envelope",
    )


def test_required_modules_have_expected_roles():
    assert ensure_entrypoint_role(UNIFIED_LAUNCHER_ENTRY_ID, EntrypointRole.SUB_ENTRY)
    assert ensure_entrypoint_role(
        "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        EntrypointRole.STAGE_ENTRY,
    )
    assert ensure_entrypoint_role("core.openclawd:OpenClawd.process", EntrypointRole.INTERNAL_ENTRY)
    assert ensure_entrypoint_role(
        "core.command_router:CommandRouter.route_envelope",
        EntrypointRole.INTERNAL_ENTRY,
    )


def test_compat_fallback_legacy_entries_are_not_main():
    compat_entries = [
        record for record in ENTRYPOINT_ROLE_REGISTRY.values() if record.role == EntrypointRole.COMPAT_FALLBACK_LEGACY
    ]
    assert compat_entries
    assert all(record.non_main_reason for record in compat_entries)
    assert ensure_entrypoint_role(LEGACY_DOCKER_LAUNCHER_ENTRY_ID, EntrypointRole.COMPAT_FALLBACK_LEGACY)
    assert ensure_entrypoint_role(LEGACY_WINDOWS_RUN_UI_ENTRY_ID, EntrypointRole.COMPAT_FALLBACK_LEGACY)


def test_android_v2_mainline_bridge_anchors_are_present():
    assert "InputRouter.kt" in ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["android_source_uplink"]
    assert ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_startup_authority"] == MAIN_ENTRY_ID
    assert ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_subordinate_launcher"] == UNIFIED_LAUNCHER_ENTRY_ID
    assert ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_gateway_ingress"] == "galaxy_gateway.routes.chat:chat_endpoint"
    assert (
        ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_mainline_runtime_shell"]
        == "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request"
    )
    assert ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_mainline_subject_core"] == "core.openclawd:OpenClawd.process"


def test_main_py_enforces_main_entry_role_contract():
    src = _read("main.py")
    assert "assert_single_unique_main_entrypoint()" in src
    assert "ensure_entrypoint_role(MAIN_ENTRY_ID, EntrypointRole.UNIQUE_MAIN)" in src
    # 子入口路径**不许再硬编码**。
    #
    # 这条原本断言的字面量就是 ``PROJECT_ROOT / "unified_launcher.py"``。
    # 启动器统一删掉那个本体之后，硬编码那份让**每一次正常启动**都停在
    # "子入口缺失"（doctor 走的是另一条分支，照样全绿，所以没人发现）。
    # 现在路径从契约的 module_path 取 —— 同一件事只有一处出处。
    assert "get_entrypoint_record(UNIFIED_LAUNCHER_ENTRY_ID)" in src, "子入口路径必须从入口契约取，不能再硬编码"
    assert 'PROJECT_ROOT / "unified_launcher.py"' not in src, "不许退回硬编码已删除的启动器路径"


def test_service_orchestration_enforces_sub_entry_role_contract():
    """从属角色的校验必须还在跑 —— 换了地方，没有消失。

    原来在 ``unified_launcher.main()`` 的开头。那个 CLI 外壳随本体删除后，
    校验一度**没有任何地方在跑**：契约里的登记还在，却再也没人核对，
    于是登记退化成一份没人读的声明。现在搬到 ``GalaxyUnified.start()``
    —— 真正开始编排的那一刻，与原来的时机一致。
    """
    src = _read("launcher/services.py")
    assert "ensure_entrypoint_role(UNIFIED_LAUNCHER_ENTRY_ID, EntrypointRole.SUB_ENTRY)" in src


def test_stage_internal_role_constants_are_declared():
    import re

    assert re.search(
        r"DESKTOP_PRESENCE_RUNTIME_ENTRYPOINT_ROLE\s*:\s*str\s*=\s*[\"']stage_entry[\"']",
        _read("core/desktop_presence_runtime.py"),
    )
    assert re.search(
        r"OPENCLAWD_ENTRYPOINT_ROLE\s*:\s*str\s*=\s*[\"']internal_entry[\"']",
        _read("core/openclawd.py"),
    )
    assert re.search(
        r"COMMAND_ROUTER_ENTRYPOINT_ROLE\s*:\s*str\s*=\s*[\"']internal_entry[\"']",
        _read("core/command_router.py"),
    )


def test_gateway_chat_still_delegates_to_runtime_shell():
    src = _read("galaxy_gateway/routes/chat.py")
    assert "get_desktop_presence_runtime" in src
    assert "runtime.handle_request(" in src


def test_snapshot_reports_single_main_and_android_anchor():
    snap = build_entrypoint_role_snapshot()
    assert snap["single_unique_main_entrypoint"] is True
    assert "android_v2_mainline_bridge_anchors" in snap
    assert snap["role_counts"]["unique_main"] == 1


def test_legacy_launchers_point_to_main_py_first():
    run_ui_src = _read("enhancements/clients/windows_client/run_ui.py")
    assert "Authoritative startup path: python main.py" in run_ui_src
    # "还有第二条直接调用路径"这句已经不成立了：unified_launcher.py 已删除，
    # main.py 是唯一入口。指路只剩一条，这正是统一的目的。
    assert "unified_launcher" not in run_ui_src, "不该再指向已删除的启动器"

    # 融合(域7):scripts/launcher_v2.py(自述非权威、仅 subprocess 转发 main.py 的
    # 死 shim)已删除——入口收敛,不再保留第三个入口壳。
    import pathlib as _pl

    assert not (_pl.Path(__file__).parent.parent / "scripts" / "launcher_v2.py").exists()


def test_legacy_registry_recommendations_demote_non_main_launchers():
    from core.legacy_purge_registry import get_purge_entry
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    run_ui_entry = LEGACY_PATH_REGISTRY["enhancements.clients.windows_client.run_ui"]
    assert "python main.py" in run_ui_entry.recommendation
    assert "unified_launcher" not in run_ui_entry.recommendation, "不该再推荐已删除的启动器"

    run_ui_purge_entry = get_purge_entry("enhancements/clients/windows_client/run_ui.py")
    assert run_ui_purge_entry is not None
    assert run_ui_purge_entry.canonical_replacement.startswith("python main.py")

    start_galaxy_entry = get_purge_entry("start_galaxy.py")
    assert start_galaxy_entry is not None
    assert start_galaxy_entry.canonical_replacement.startswith("python main.py")
