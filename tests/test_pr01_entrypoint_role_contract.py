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
    EntrypointRole,
    PRIMARY_STARTUP_CHAIN,
    assert_single_unique_main_entrypoint,
    build_entrypoint_role_snapshot,
    ensure_entrypoint_role,
)

REPO_ROOT = Path(__file__).parent.parent


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_contract_sentinel_present():
    assert ENTRYPOINT_ROLE_CONTRACT_SENTINEL.startswith(
        "ENTRYPOINT_ROLE_CONTRACT_SENTINEL::PR01::"
    )


def test_single_unique_main_entrypoint_is_main_py():
    assert assert_single_unique_main_entrypoint()
    assert ensure_entrypoint_role("main.py:main", EntrypointRole.UNIQUE_MAIN)


def test_primary_startup_chain_is_stable():
    assert PRIMARY_STARTUP_CHAIN == (
        "main.py:main",
        "unified_launcher.py:main",
        "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        "core.openclawd:OpenClawd.process",
        "core.command_router:CommandRouter.route_envelope",
    )


def test_required_modules_have_expected_roles():
    assert ensure_entrypoint_role(
        "unified_launcher.py:main", EntrypointRole.SUB_ENTRY
    )
    assert ensure_entrypoint_role(
        "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        EntrypointRole.STAGE_ENTRY,
    )
    assert ensure_entrypoint_role(
        "core.openclawd:OpenClawd.process", EntrypointRole.INTERNAL_ENTRY
    )
    assert ensure_entrypoint_role(
        "core.command_router:CommandRouter.route_envelope",
        EntrypointRole.INTERNAL_ENTRY,
    )


def test_compat_fallback_legacy_entries_are_not_main():
    compat_entries = [
        record
        for record in ENTRYPOINT_ROLE_REGISTRY.values()
        if record.role == EntrypointRole.COMPAT_FALLBACK_LEGACY
    ]
    assert compat_entries
    assert all(record.non_main_reason for record in compat_entries)
    assert all(record.role != EntrypointRole.UNIQUE_MAIN for record in compat_entries)


def test_android_v2_mainline_bridge_anchors_are_present():
    assert "InputRouter.kt" in ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["android_source_uplink"]
    assert (
        ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_gateway_ingress"]
        == "galaxy_gateway.routes.chat:chat_endpoint"
    )
    assert (
        ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_mainline_runtime_shell"]
        == "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request"
    )
    assert (
        ANDROID_V2_MAINLINE_BRIDGE_ANCHORS["v2_mainline_subject_core"]
        == "core.openclawd:OpenClawd.process"
    )


def test_main_py_enforces_main_entry_role_contract():
    src = _read("main.py")
    assert "assert_single_unique_main_entrypoint()" in src
    assert 'ensure_entrypoint_role("main.py:main", EntrypointRole.UNIQUE_MAIN)' in src
    assert 'launcher_path = PROJECT_ROOT / "unified_launcher.py"' in src


def test_unified_launcher_enforces_sub_entry_role_contract():
    src = _read("unified_launcher.py")
    assert 'ensure_entrypoint_role("unified_launcher.py:main", EntrypointRole.SUB_ENTRY)' in src
    assert "从属组件" in src


def test_stage_internal_role_constants_are_declared():
    assert 'DESKTOP_PRESENCE_RUNTIME_ENTRYPOINT_ROLE: str = "stage_entry"' in _read(
        "core/desktop_presence_runtime.py"
    )
    assert 'OPENCLAWD_ENTRYPOINT_ROLE: str = "internal_entry"' in _read(
        "core/openclawd.py"
    )
    assert 'COMMAND_ROUTER_ENTRYPOINT_ROLE: str = "internal_entry"' in _read(
        "core/command_router.py"
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

