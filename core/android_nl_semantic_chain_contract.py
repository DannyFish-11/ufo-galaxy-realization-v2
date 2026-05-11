"""
core/android_nl_semantic_chain_contract.py
==========================================
Android NL 语义链路契约 — 机器可验证的 source/carrier vs semantic-authority 分离声明。

背景（来自 audit/DUAL_REPO_REAL_CHAIN_BASELINE_2026.md P2）
-----------------------------------------------------------
双仓系统存在三条 NL 入路：

1. **V2/桌面本地 NL 主链**
   用户通过 `/api/v1/chat` 或 DesktopPresenceRuntime.handle_request(source="chat") 发送 NL
   → DesktopPresenceRuntime (source="chat")
   → OpenClawd + AgentKernel + MultiLLMRouter（LLM 语义权威主链）

2. **Android 本地 NL 入口**（仅在 Android 设备本地执行，不经过 V2 LLM 链）
   Android 端本地触发（语音/输入）
   → GoalNormalizer（NL goal → NormalizedGoal，仅结构化，无 LLM）
   → LocalGoalExecutor → LocalPlannerService（本地任务分解，无 LLM）
   → EdgeExecutor（本地 UI 执行）
   **此路径：V2 LLM 语义链未参与**

3. **Android 跨设备 NL 入口**（Android 作为 carrier，V2 是 semantic authority）
   Android 端 GoalNormalizer 规范化后 → AIP v3 goal_execution 消息 → gateway
   → DesktopPresenceRuntime (source="android_goal_execution")
   → OpenClawd + AgentKernel + MultiLLMRouter（LLM 语义权威主链）
   **此路径：V2 LLM 语义链参与；Android 是 carrier，V2 是 semantic authority**

职责边界（契约层钉死）
----------------------
- ``GoalNormalizer`` (Android nlp/GoalNormalizer.kt)：
  * 角色：NL goal 结构化规范化（字符串 → NormalizedGoal 数据类）
  * **不做** LLM 语义推理
  * **不做** 意图分类
  * **不做** 上下文理解
  * **不是** LLM semantic authority

- ``LocalPlannerService`` (Android inference/LocalPlannerService.kt)：
  * 角色：本地任务分解（goal → steps，rule-based 或本地模型，如 MobileVLM）
  * **不做** 系统级 LLM 语义推理
  * **不是** 语义权威（semantic authority）
  * 仅在 Android 本地 NL 路径（路径 2）中运行
  * V2 无法感知 LocalPlannerService 的存在（它不发 V2 消息）

- **V2 OpenClawd + AgentKernel + MultiLLMRouter**：
  * 角色：系统的唯一 LLM 语义权威（semantic authority）
  * 处理所有经 gateway 进入的 NL 请求（路径 1 + 路径 3）
  * ``ingress_carrier_context.semantic_authority`` 字段必须为 ``"v2_openclawd"``

机器可验证契约常量
------------------
本模块提供可被测试和 operator surfaces 引用的机器可验证常量，以避免
"Android 本地结构化逻辑被误判为系统级 LLM semantic authority"。

用法
----
::

    from core.android_nl_semantic_chain_contract import (
        GOAL_NORMALIZER_ROLE,
        LOCAL_PLANNER_SERVICE_ROLE,
        V2_SEMANTIC_AUTHORITY,
        ANDROID_NL_CARRIER_SOURCE,
        ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
        ANDROID_LOCAL_NL_PATH_TYPE,
        DESKTOP_DIRECT_NL_PATH_TYPE,
        NL_PATH_TYPES,
        ANDROID_CARRIER_SOURCES,
        is_android_nl_carrier,
        is_v2_semantic_authority_path,
        build_android_nl_carrier_context,
        ANDROID_NL_SEMANTIC_CHAIN_CONTRACT_SENTINEL,
    )
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Contract sentinel — presence of this constant proves the contract is loaded.
# ---------------------------------------------------------------------------

ANDROID_NL_SEMANTIC_CHAIN_CONTRACT_SENTINEL: str = (
    "ANDROID_NL_SEMANTIC_CHAIN_CONTRACT::v1 present"
)

# ---------------------------------------------------------------------------
# Component role declarations
# ---------------------------------------------------------------------------

#: Android-side GoalNormalizer role: structural normalization of a raw NL goal
#: string into a NormalizedGoal data object.  This is NOT LLM semantic reasoning.
GOAL_NORMALIZER_ROLE: str = "android_structural_normalization"

#: Android-side LocalPlannerService role: local task decomposition (goal → steps).
#: This is a rule-based or device-local model planner.  It is NOT system-level
#: LLM semantic reasoning and is NOT the semantic authority.
LOCAL_PLANNER_SERVICE_ROLE: str = "android_local_task_decomposition"

#: V2's OpenClawd + AgentKernel + MultiLLMRouter — the sole LLM semantic authority.
V2_SEMANTIC_AUTHORITY: str = "v2_openclawd"

# ---------------------------------------------------------------------------
# Source/carrier identifiers
# ---------------------------------------------------------------------------

#: DPR source tag for Android cross-device NL requests (via AIP v3 goal_execution).
ANDROID_NL_CARRIER_SOURCE: str = "android_goal_execution"

#: All DPR source tags that originate from an Android device carrier.
ANDROID_CARRIER_SOURCES: frozenset = frozenset(
    {"android_goal_execution", "android_vision"}
)

# ---------------------------------------------------------------------------
# NL path type identifiers (stamped in ingress_carrier_context.nl_path_type)
# ---------------------------------------------------------------------------

#: Android cross-device NL: Android is the carrier, V2 is the semantic authority.
ANDROID_CROSS_DEVICE_NL_PATH_TYPE: str = "android_cross_device_nl"

#: Android local NL: goal stays on device, V2 LLM chain is NOT involved.
#: GoalNormalizer → LocalGoalExecutor → LocalPlannerService → EdgeExecutor (local only).
ANDROID_LOCAL_NL_PATH_TYPE: str = "android_local_nl"

#: Desktop/V2 direct NL: user interacts via chat endpoint on the V2 host machine.
DESKTOP_DIRECT_NL_PATH_TYPE: str = "desktop_direct_nl"

#: All valid nl_path_type values.
NL_PATH_TYPES: frozenset = frozenset(
    {
        ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
        ANDROID_LOCAL_NL_PATH_TYPE,
        DESKTOP_DIRECT_NL_PATH_TYPE,
        "android_vision_nl",
    }
)

# ---------------------------------------------------------------------------
# Android participation authority boundary model (single-source contract)
# ---------------------------------------------------------------------------

ANDROID_PARTICIPATION_SIGNAL: str = "signal_participation"
ANDROID_PARTICIPATION_EXECUTION: str = "execution_participation"
ANDROID_PARTICIPATION_TAKEOVER: str = "takeover_participation"
ANDROID_PARTICIPATION_LOCAL_AUTONOMY: str = "local_autonomy_participation"
ANDROID_PARTICIPATION_AUTHORITY_ADJACENT: str = "authority_adjacent_participation"

ANDROID_PARTICIPATION_TYPES: frozenset = frozenset(
    {
        ANDROID_PARTICIPATION_SIGNAL,
        ANDROID_PARTICIPATION_EXECUTION,
        ANDROID_PARTICIPATION_TAKEOVER,
        ANDROID_PARTICIPATION_LOCAL_AUTONOMY,
        ANDROID_PARTICIPATION_AUTHORITY_ADJACENT,
    }
)

ANDROID_PARTICIPATION_BOUNDARY_MODEL: Dict[str, Dict[str, bool]] = {
    ANDROID_PARTICIPATION_SIGNAL: {
        "affects_observation": True,
        "affects_reconciliation": False,
        "may_override_v2_authority": False,
    },
    ANDROID_PARTICIPATION_EXECUTION: {
        "affects_observation": True,
        "affects_reconciliation": True,
        "may_override_v2_authority": False,
    },
    ANDROID_PARTICIPATION_TAKEOVER: {
        "affects_observation": True,
        "affects_reconciliation": True,
        "may_override_v2_authority": False,
    },
    ANDROID_PARTICIPATION_LOCAL_AUTONOMY: {
        "affects_observation": True,
        "affects_reconciliation": False,
        "may_override_v2_authority": False,
    },
    ANDROID_PARTICIPATION_AUTHORITY_ADJACENT: {
        "affects_observation": True,
        "affects_reconciliation": True,
        "may_override_v2_authority": False,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_android_nl_carrier(source: str) -> bool:
    """Return True when *source* is one of the recognized Android NL transport sources.

    The term "carrier" here refers to the **source/transport tag** used by
    ``DesktopPresenceRuntime.handle_request(source=...)`` — it identifies the
    adapter surface or gateway path that delivered the NL request.  Being an
    Android carrier does NOT mean Android is the semantic authority — the semantic
    authority is always V2 (``V2_SEMANTIC_AUTHORITY``) once the request enters DPR.

    Parameters
    ----------
    source:
        The ``source`` tag passed to ``DesktopPresenceRuntime.handle_request()``.

    Returns
    -------
    bool
        ``True`` for ``"android_goal_execution"`` and ``"android_vision"``.
        ``False`` for ``"chat"``, ``"openclawd"``, etc.
    """
    return source in ANDROID_CARRIER_SOURCES


def _normalize_participation_type(participation_type: str) -> str:
    return str(participation_type or "").strip().lower()


def is_v2_semantic_authority_path(ingress_carrier_context: Dict[str, Any]) -> bool:
    """Return True when *ingress_carrier_context* confirms V2 as semantic authority.

    Call this to machine-verify that an ingress result went through the canonical
    V2 LLM semantic chain (OpenClawd + AgentKernel + MultiLLMRouter).

    Parameters
    ----------
    ingress_carrier_context:
        The ``ingress_carrier_context`` dict from a DPR result.
    """
    return ingress_carrier_context.get("semantic_authority") == V2_SEMANTIC_AUTHORITY


def get_android_participation_boundary(participation_type: str) -> Dict[str, bool]:
    """Return canonical authority-boundary policy for the participation type."""
    key = _normalize_participation_type(participation_type)
    boundary = ANDROID_PARTICIPATION_BOUNDARY_MODEL.get(key)
    if boundary is None:
        return {
            "affects_observation": False,
            "affects_reconciliation": False,
            "may_override_v2_authority": False,
        }
    return dict(boundary)


def build_android_nl_carrier_context(
    device_id: str,
    session_id: str,
    invocation_id: str,
    nl_path_type: str = ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
    control_session_id: str = "",
    user_id: str = "default",
) -> Dict[str, Any]:
    """Build a canonical Android NL ingress_carrier_context dict.

    This is the reference builder for Android-originated NL requests.  The
    resulting dict conforms to the contract stamped by
    ``DesktopPresenceRuntime.handle_request()`` for ``source="android_goal_execution"``.

    Parameters
    ----------
    device_id:
        The Android device ID that originated the NL request.
    session_id:
        Conversation session ID.
    invocation_id:
        The ``runtime_session_id`` (correlation ID for this invocation).
    nl_path_type:
        One of the ``*_NL_PATH_TYPE`` constants defined in this module.
        Defaults to :data:`ANDROID_CROSS_DEVICE_NL_PATH_TYPE`.
    control_session_id:
        Optional control-plane session ID.
    user_id:
        User identifier.

    Returns
    -------
    dict
        Canonical carrier context that can be used in assertions or stored in
        result payloads.
    """
    return {
        "carrier": ANDROID_NL_CARRIER_SOURCE,
        "authority_chain": "DesktopPresenceRuntime.handle_request",
        "session_id": session_id,
        "user_id": user_id,
        "invocation_id": invocation_id,
        "control_session_id": control_session_id,
        "semantic_authority": V2_SEMANTIC_AUTHORITY,
        "nl_path_type": nl_path_type,
        "is_android_carrier": True,
        "device_id": device_id,
    }


# ---------------------------------------------------------------------------
# Contract assertion helpers (for use in tests)
# ---------------------------------------------------------------------------


def assert_v2_is_semantic_authority(result: Dict[str, Any], context: str = "") -> None:
    """Assert that *result* confirms V2 as the LLM semantic authority.

    Raises AssertionError with a descriptive message if the assertion fails.
    Intended for use in integration tests to machine-verify the semantic chain.

    Parameters
    ----------
    result:
        A dict returned by ``DesktopPresenceRuntime.handle_request()``.
    context:
        Optional string identifying the test context for clearer error messages.
    """
    icc = result.get("ingress_carrier_context", {})
    prefix = f"[{context}] " if context else ""
    assert isinstance(icc, dict), (
        f"{prefix}ingress_carrier_context must be a dict; got {type(icc).__name__}"
    )
    semantic_auth = icc.get("semantic_authority", "")
    assert semantic_auth == V2_SEMANTIC_AUTHORITY, (
        f"{prefix}semantic_authority must be {V2_SEMANTIC_AUTHORITY!r} — "
        f"V2 OpenClawd + AgentKernel + MultiLLMRouter is the sole LLM semantic authority. "
        f"Got {semantic_auth!r}. Android-side GoalNormalizer and LocalPlannerService are "
        f"carrier/structural/local-planning components, NOT the semantic authority."
    )


def assert_android_nl_carrier(result: Dict[str, Any], context: str = "") -> None:
    """Assert that *result* confirms an Android device is the NL carrier.

    This does NOT check semantic_authority — use :func:`assert_v2_is_semantic_authority`
    for that.  This function only checks that the carrier was Android.

    Parameters
    ----------
    result:
        A dict returned by ``DesktopPresenceRuntime.handle_request()``.
    context:
        Optional string identifying the test context for clearer error messages.
    """
    icc = result.get("ingress_carrier_context", {})
    prefix = f"[{context}] " if context else ""
    assert isinstance(icc, dict), (
        f"{prefix}ingress_carrier_context must be a dict; got {type(icc).__name__}"
    )
    is_android = icc.get("is_android_carrier", False)
    assert is_android is True, (
        f"{prefix}is_android_carrier must be True for Android NL carrier paths. "
        f"Got {is_android!r}. Carrier: {icc.get('carrier')!r}"
    )


def assert_nl_path_type(
    result: Dict[str, Any],
    expected_nl_path_type: str,
    context: str = "",
) -> None:
    """Assert that *result* has the expected ``nl_path_type`` in its carrier context.

    Parameters
    ----------
    result:
        A dict returned by ``DesktopPresenceRuntime.handle_request()``.
    expected_nl_path_type:
        One of the ``*_NL_PATH_TYPE`` constants (e.g. ``ANDROID_CROSS_DEVICE_NL_PATH_TYPE``).
    context:
        Optional string for error message context.
    """
    icc = result.get("ingress_carrier_context", {})
    prefix = f"[{context}] " if context else ""
    actual = icc.get("nl_path_type", "")
    assert actual == expected_nl_path_type, (
        f"{prefix}nl_path_type must be {expected_nl_path_type!r}. "
        f"Got {actual!r}. Full carrier context: {icc}"
    )
