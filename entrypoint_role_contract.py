#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
entrypoint_role_contract.py
===========================

PR-01 startup/entrypoint role contract.

This module codifies one authoritative entry hierarchy without creating a new
startup framework:

    main.py (唯一主入口)
      -> unified_launcher.py (子入口，承接 Phase 4-6)
         -> DesktopPresenceRuntime.handle_request (阶段入口：runtime shell)
            -> OpenClawd.process (内部阶段入口：subject core)
               -> CommandRouter.route_envelope (内部阶段入口：cross-device substrate)

Compat/fallback/legacy surfaces remain available but are explicitly non-main.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

ENTRYPOINT_ROLE_CONTRACT_SENTINEL: str = (
    "ENTRYPOINT_ROLE_CONTRACT_SENTINEL::PR01::single-main-entrypoint-contract-v1"
)


class EntrypointRole(str, Enum):
    UNIQUE_MAIN = "unique_main"
    SUB_ENTRY = "sub_entry"
    STAGE_ENTRY = "stage_entry"
    INTERNAL_ENTRY = "internal_entry"
    COMPAT_FALLBACK_LEGACY = "compat_fallback_legacy"


@dataclass(frozen=True)
class EntrypointRecord:
    entry_id: str
    role: EntrypointRole
    module_path: str
    trigger_boundary: str
    next_hop: Optional[str] = None
    non_main_reason: Optional[str] = None


ENTRYPOINT_ROLE_REGISTRY: Dict[str, EntrypointRecord] = {
    "main.py:main": EntrypointRecord(
        entry_id="main.py:main",
        role=EntrypointRole.UNIQUE_MAIN,
        module_path="main.py",
        trigger_boundary="process startup entrypoint",
        next_hop="unified_launcher.py:main",
    ),
    "unified_launcher.py:main": EntrypointRecord(
        entry_id="unified_launcher.py:main",
        role=EntrypointRole.SUB_ENTRY,
        module_path="unified_launcher.py",
        trigger_boundary="phase delegate (Phase 4-6) / direct advanced invocation",
        next_hop="core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        non_main_reason="subordinate launcher component",
    ),
    "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request": EntrypointRecord(
        entry_id="core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        role=EntrypointRole.STAGE_ENTRY,
        module_path="core/desktop_presence_runtime.py",
        trigger_boundary="runtime shell request lifecycle boundary",
        next_hop="core.openclawd:OpenClawd.process",
        non_main_reason="runtime stage entry only",
    ),
    "core.openclawd:OpenClawd.process": EntrypointRecord(
        entry_id="core.openclawd:OpenClawd.process",
        role=EntrypointRole.INTERNAL_ENTRY,
        module_path="core/openclawd.py",
        trigger_boundary="subject-core liminal cognition boundary",
        next_hop="core.command_router:CommandRouter.route_envelope",
        non_main_reason="internal subject-core stage",
    ),
    "core.command_router:CommandRouter.route_envelope": EntrypointRecord(
        entry_id="core.command_router:CommandRouter.route_envelope",
        role=EntrypointRole.INTERNAL_ENTRY,
        module_path="core/command_router.py",
        trigger_boundary="cross-device dispatch substrate boundary",
        non_main_reason="internal dispatch substrate stage",
    ),
    "core.routes.chat:chat": EntrypointRecord(
        entry_id="core.routes.chat:chat",
        role=EntrypointRole.COMPAT_FALLBACK_LEGACY,
        module_path="core/routes/chat.py",
        trigger_boundary="compat HTTP chat adapter surface",
        next_hop="core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        non_main_reason="compat adapter surface",
    ),
    "galaxy_gateway.routes.chat:chat_endpoint": EntrypointRecord(
        entry_id="galaxy_gateway.routes.chat:chat_endpoint",
        role=EntrypointRole.COMPAT_FALLBACK_LEGACY,
        module_path="galaxy_gateway/routes/chat.py",
        trigger_boundary="gateway adapter ingress for Android/WS-compatible traffic",
        next_hop="core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
        non_main_reason="gateway adapter surface",
    ),
    "dashboard.backend.main:app": EntrypointRecord(
        entry_id="dashboard.backend.main:app",
        role=EntrypointRole.COMPAT_FALLBACK_LEGACY,
        module_path="dashboard/backend/main.py",
        trigger_boundary="legacy dashboard surface",
        non_main_reason="legacy compatibility surface",
    ),
}


PRIMARY_STARTUP_CHAIN: Tuple[str, ...] = (
    "main.py:main",
    "unified_launcher.py:main",
    "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request",
    "core.openclawd:OpenClawd.process",
    "core.command_router:CommandRouter.route_envelope",
)


ANDROID_V2_MAINLINE_BRIDGE_ANCHORS: Dict[str, str] = {
    "android_source_uplink": (
        "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/input/InputRouter.kt::"
        "route() -> TASK_SUBMIT websocket uplink"
    ),
    "android_protocol_contract": (
        "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt::"
        "MsgType.TASK_SUBMIT/TASK_ASSIGN/TASK_RESULT"
    ),
    "v2_gateway_ingress": "galaxy_gateway.routes.chat:chat_endpoint",
    "v2_mainline_runtime_shell": (
        "core.desktop_presence_runtime:DesktopPresenceRuntime.handle_request"
    ),
    "v2_mainline_subject_core": "core.openclawd:OpenClawd.process",
}


def get_entrypoint_record(entry_id: str) -> Optional[EntrypointRecord]:
    return ENTRYPOINT_ROLE_REGISTRY.get(entry_id)


def ensure_entrypoint_role(entry_id: str, expected_role: EntrypointRole) -> bool:
    record = get_entrypoint_record(entry_id)
    return record is not None and record.role == expected_role


def assert_single_unique_main_entrypoint() -> bool:
    main_entries = [
        record.entry_id
        for record in ENTRYPOINT_ROLE_REGISTRY.values()
        if record.role == EntrypointRole.UNIQUE_MAIN
    ]
    return main_entries == ["main.py:main"]


def build_entrypoint_role_snapshot() -> Dict[str, object]:
    role_counts: Dict[str, int] = {}
    for record in ENTRYPOINT_ROLE_REGISTRY.values():
        role_counts[record.role.value] = role_counts.get(record.role.value, 0) + 1
    return {
        "sentinel": ENTRYPOINT_ROLE_CONTRACT_SENTINEL,
        "single_unique_main_entrypoint": assert_single_unique_main_entrypoint(),
        "primary_startup_chain": list(PRIMARY_STARTUP_CHAIN),
        "role_counts": role_counts,
        "android_v2_mainline_bridge_anchors": dict(ANDROID_V2_MAINLINE_BRIDGE_ANCHORS),
        "entries": [record.entry_id for record in ENTRYPOINT_ROLE_REGISTRY.values()],
    }


def list_non_main_entries() -> List[str]:
    return [
        record.entry_id
        for record in ENTRYPOINT_ROLE_REGISTRY.values()
        if record.role != EntrypointRole.UNIQUE_MAIN
    ]

