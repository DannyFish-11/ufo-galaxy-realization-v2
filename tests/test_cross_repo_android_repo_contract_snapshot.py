from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from contracts.cross_repo_schema_version_gate import (
    ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
    REQUIRED_AIP_MESSAGE_TYPES,
)


def _android_repo_root() -> Path:
    raw = os.environ.get("ANDROID_REPO_ROOT", "").strip()
    if not raw:
        pytest.skip("ANDROID_REPO_ROOT not set; skip direct Android repo contract snapshot checks.")
    root = Path(raw)
    if not root.exists():
        pytest.skip(f"ANDROID_REPO_ROOT does not exist: {root}")
    return root


def _read_android_file(relative_path: str) -> str:
    root = _android_repo_root()
    path = root / relative_path
    if not path.exists():
        pytest.skip(f"Android file not found: {path}")
    return path.read_text(encoding="utf-8")


# Android MsgType 的 canonical 位置:客户端枚举早已迁到 shared-protocol
# (Android + WearOS 共用的唯一 wire 权威);旧 AipModels.kt 仅作历史回退。
# 此前本测试只读 AipModels.kt → 迁移后一直 "Unable to locate MsgType enum"。
_ANDROID_MSGTYPE_PATHS = (
    "shared-protocol/src/main/java/com/ufo/galaxy/shared/protocol/MsgType.kt",
    "app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt",  # legacy fallback
)


def _read_android_msg_type_source() -> str:
    root = _android_repo_root()
    for rel in _ANDROID_MSGTYPE_PATHS:
        path = root / rel
        if path.exists():
            return path.read_text(encoding="utf-8")
    pytest.skip(f"Android MsgType source not found in any of: {_ANDROID_MSGTYPE_PATHS}")


def _extract_android_msg_type_wire_values(aip_models_source: str) -> set[str]:
    # Keep this extraction scoped to the stable MsgType enum shape
    # (shared-protocol/MsgType.kt, legacy AipModels.kt 同型):
    # enum class MsgType(val value: String) { ... }
    # If Android changes MsgType declaration syntax materially, update this
    # parser together with the cross-repo compatibility tests.
    enum_match = re.search(
        r"enum class MsgType\(val value: String\)\s*\{(.*?)\n\}",
        aip_models_source,
        flags=re.DOTALL,
    )
    assert enum_match is not None, "Unable to locate Android MsgType enum"
    return set(re.findall(r"\(\s*\"([a-z0-9_]+)\"\s*\)", enum_match.group(1)))


def test_android_msg_type_enum_covers_v2_required_message_types() -> None:
    aip_models_source = _read_android_msg_type_source()
    wire_values = _extract_android_msg_type_wire_values(aip_models_source)
    missing = sorted(REQUIRED_AIP_MESSAGE_TYPES - wire_values)
    assert not missing, (
        "Android MsgType is missing V2 required message types: "
        f"{missing}. Update Android MsgType + V2 gate constants together."
    )


def test_android_schema_and_dedupe_tokens_for_v2_contract_are_present() -> None:
    root = _android_repo_root()
    aip_models_source = _read_android_msg_type_source()
    msg_type_values = _extract_android_msg_type_wire_values(aip_models_source)
    kotlin_paths = list(root.rglob("*.kt"))
    file_cache: dict[Path, str] = {}

    def _contains_token(token: str) -> bool:
        for path in kotlin_paths:
            content = file_cache.get(path)
            if content is None:
                content = path.read_text(encoding="utf-8")
                file_cache[path] = content
            if token in content:
                return True
        return False

    def _assert_any(tokens: list[str], category: str) -> None:
        assert any(_contains_token(token) for token in tokens), (
            f"Android repository is missing required {category} token(s): {tokens}. "
            "This can break V2 replay/recovery/dedupe compatibility."
        )

    _assert_any(["idempotency_key"], "result idempotency")
    _assert_any(["completion_emission_id", "result_id", "completion_id", "emission_id"], "result emission identity")
    _assert_any(["contract_id", "session_id", "runtime_session_id"], "reconciliation scope identity")
    _assert_any(
        ["reconciliation_id", "signal_id", "handoff_id", "event_id", "result_id"],
        "reconciliation event identity",
    )

    if "offline_replay_result" in msg_type_values:
        for replay_token in ["replay_session_id", "replay_item_id", "replay_seq"]:
            assert _contains_token(replay_token), (
                f"Android replay contract token {replay_token!r} missing while " "offline_replay_result is declared."
            )


def test_android_completion_closure_contract_schema_version_matches_v2_gate() -> None:
    source = _read_android_file("app/src/main/java/com/ufo/galaxy/runtime/AndroidCompletionClosureUplinkContract.kt")
    schema_match = re.search(r'const val SCHEMA_VERSION\s*=\s*"([^"]+)"', source)
    assert schema_match is not None, "AndroidCompletionClosureUplinkContract must declare SCHEMA_VERSION."
    assert schema_match.group(1) == ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION

    for required_wire_key in [
        "completion_closure_uplink_schema_version",
        "v2_uplink_acknowledged",
        "v2_reconciliation_acknowledged",
        "v2_canonical_truth_completed",
        "v2_mature_closure_achieved",
        "outward_truth_surface_class",
    ]:
        assert (
            required_wire_key in source
        ), f"AndroidCompletionClosureUplinkContract missing required wire key {required_wire_key!r}."


def test_android_cross_repo_gate_covers_recovery_readiness_and_diagnostics_surfaces() -> None:
    source = _read_android_file("app/src/main/java/com/ufo/galaxy/protocol/CrossRepoConsistencyGate.kt")
    for required_check in [
        "checkReconnectRecoveryStates",
        "checkCapabilityReadinessDescriptors",
        "checkObservabilityTraceFieldNames",
        "checkReconciliationSignalKinds",
    ]:
        assert (
            f"fun {required_check}" in source
        ), f"Android CrossRepoConsistencyGate missing {required_check}() enforcement surface."
        assert (
            f"{required_check}()" in source
        ), f"Android CrossRepoConsistencyGate.runAllGates does not include {required_check}()."
