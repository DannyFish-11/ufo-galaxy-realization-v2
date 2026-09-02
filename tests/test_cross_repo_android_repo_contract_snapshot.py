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
    """读安卓仓里的一个源文件。**文件不存在时失败,不跳过。**

    这里原本是 ``pytest.skip(f"Android file not found: {path}")``。

    问题在于这道门的**全部作用**就是"安卓那边的契约面还在不在、有没有漂"。
    一旦被读的文件被改名或挪走 —— 而那正是最典型的漂移形态 —— 跳过会让这道门
    变绿,并且绿得毫无痕迹:CI 摘要里只是少了几个用例,没有任何东西提示"该检查的
    没检查"。守卫在最该报警的那一刻恰好静音。

    跳过只对一种情况成立:**根本没有跨仓 checkout**(本机开发)。那由
    :func:`_android_repo_root` 判定。走到这里就说明 checkout 是在的,
    此时文件缺失是真实的契约漂移。
    """
    root = _android_repo_root()
    path = root / relative_path
    assert path.exists(), (
        f"安卓仓里找不到契约面文件: {relative_path}\n"
        f"(在 {root} 下查找)\n"
        "这不是环境问题 —— 跨仓 checkout 是在的。文件被改名/挪走/删除就是这道门要拦的漂移本身;"
        "如果这是有意的迁移,请把本文件里的路径一并更新,而不是让它继续静默跳过。"
    )
    return path.read_text(encoding="utf-8")


# Android MsgType 的 canonical 位置:客户端枚举早已迁到 shared-protocol
# (Android + WearOS 共用的唯一 wire 权威);旧 AipModels.kt 仅作历史回退。
# 此前本测试只读 AipModels.kt → 迁移后一直 "Unable to locate MsgType enum"。
_ANDROID_MSGTYPE_PATHS = (
    "shared-protocol/src/main/java/com/ufo/galaxy/shared/protocol/MsgType.kt",
    "app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt",  # legacy fallback
)


def _read_android_msg_type_source() -> str:
    """定位并读取安卓侧的 ``MsgType`` 枚举源。找不到时失败,不跳过 —— 理由同
    :func:`_read_android_file`。

    这一处尤其不能跳:``MsgType`` 是两仓之间的 wire 权威。它要是找不到了,
    "两边消息类型一致"这件事就完全没人在验,而门照样是绿的。
    """
    root = _android_repo_root()
    for rel in _ANDROID_MSGTYPE_PATHS:
        path = root / rel
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise AssertionError(
        f"安卓仓里定位不到 MsgType 枚举,试过: {list(_ANDROID_MSGTYPE_PATHS)}(在 {root} 下)。\n"
        "MsgType 是两仓的 wire 权威,找不到它等于这道门什么都没验。"
        "枚举若已迁走,请把新路径加进 _ANDROID_MSGTYPE_PATHS。"
    )


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


# ── 这道门自己的防退化守卫 ────────────────────────────────────────────────────
#
# 上面把"文件找不到"从 skip 改成了 fail。改回去很容易(看起来只是让 CI 少红几次),
# 而改回去之后没有任何东西会提示"这道门已经不再守了"—— 它会安静地一直绿。
# 下面两条把两种环境下各自该有的行为钉死。


def test_missing_contract_file_fails_instead_of_skipping(tmp_path, monkeypatch):
    """跨仓 checkout 在、但契约面文件不见了 —— 必须失败。

    这正是这道门存在的理由:文件被改名/挪走/删除就是最典型的契约漂移。
    改前它 skip,于是"安卓仓把这些文件全删了"这个场景下,门是**绿**的
    (实测:4 skipped)。
    """
    monkeypatch.setenv("ANDROID_REPO_ROOT", str(tmp_path))
    with pytest.raises(AssertionError, match="找不到契约面文件"):
        _read_android_file("app/src/main/java/com/ufo/galaxy/protocol/CrossRepoConsistencyGate.kt")

    with pytest.raises(AssertionError, match="定位不到 MsgType"):
        _read_android_msg_type_source()


def test_absent_cross_repo_checkout_still_skips(monkeypatch):
    """**没有**跨仓 checkout 时仍然 skip —— 本机开发不该被这道门挡住。

    区别在于:那是"这台机器上没有安卓仓"(环境),不是"安卓仓里没有这个文件"(漂移)。
    两者混为一谈正是改前的问题。
    """
    monkeypatch.delenv("ANDROID_REPO_ROOT", raising=False)
    with pytest.raises(pytest.skip.Exception):
        _android_repo_root()
