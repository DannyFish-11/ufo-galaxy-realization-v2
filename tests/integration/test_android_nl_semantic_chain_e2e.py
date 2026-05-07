"""tests/integration/test_android_nl_semantic_chain_e2e.py
============================================================
Android NL 语义链路端到端证明测试

目标（来自 audit/DUAL_REPO_REAL_CHAIN_BASELINE_2026.md P2）
----------------------------------------------------------
把 "Android 本地 NL vs 跨设备 NL" 从 "认知上大致清楚" 推进到
"代码、契约、测试三者一致"。

测试覆盖
--------
1. **TestGoalNormalizerBoundaryContract**
   - GoalNormalizer 是结构化规范化组件，不是 LLM semantic authority
   - 契约常量机器可验证

2. **TestLocalPlannerServiceBoundaryContract**
   - LocalPlannerService 是本地 task decomposition，不是 LLM semantic authority
   - LocalPlannerService 不在 V2 侧运行

3. **TestAndroidCrossDeviceNLToV2SemanticChain**
   - Android 通过 goal_execution 发 NL → V2 DPR → OpenClawd（LLM semantic authority）
   - ingress_carrier_context.carrier == "android_goal_execution"
   - ingress_carrier_context.semantic_authority == "v2_openclawd"
   - ingress_carrier_context.nl_path_type == "android_cross_device_nl"
   - ingress_carrier_context.is_android_carrier == True

4. **TestDesktopDirectNLPath**
   - 桌面直接 NL 路径（source="chat"）正确标记为 desktop_direct_nl
   - semantic_authority 同样是 "v2_openclawd"

5. **TestSemanticAuthorityIsAlwaysV2**
   - 所有经 DPR 处理的路径，semantic_authority 均为 "v2_openclawd"
   - 不存在 carrier 决定 semantic authority 的情况

6. **TestAndroidNLCarrierVsSemanticAuthorityContracts**
   - 使用 contract 模块的断言辅助函数进行机器可验证测试

7. **TestGoalExecutionHandlerUsesCorrectSource**
   - gateway goal_execution 处理器使用 source="android_goal_execution"，不再用 "chat"
   - 确保 carrier 识别不被误标

Evidence base
-------------
- core/desktop_presence_runtime.py (DPR, source dispatch, ingress_carrier_context stamp)
- core/android_nl_semantic_chain_contract.py (contract constants and helpers)
- galaxy_gateway/android/handlers/goal_execution.py (Android goal_execution handler)
- tests/integration/stubs/llm_contract_stub.py (LLM contract stub)
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_nl_e2e_canonical_path.py pattern)
# ---------------------------------------------------------------------------


def _reset_openclawd_singleton() -> None:
    """Reset the OpenClawd singleton so each test gets a fresh instance."""
    try:
        import core.openclawd as _oc_mod
        _oc_mod._openclawd_instance = None
    except Exception:
        pass
    try:
        from core.unified.llm_router import reset_unified_llm_router
        reset_unified_llm_router()
    except Exception:
        pass
    try:
        from core.session_execution_lane import reset_session_execution_lane_manager
        reset_session_execution_lane_manager()
    except Exception:
        pass


def _reset_dpr_singleton() -> None:
    """Reset the DesktopPresenceRuntime singleton."""
    try:
        import core.desktop_presence_runtime as _dpr_mod
        _dpr_mod._desktop_presence_runtime = None
    except Exception:
        pass


def _make_stub():
    """Return a fresh LLMContractStub."""
    from tests.integration.stubs.llm_contract_stub import LLMContractStub
    return LLMContractStub()


def _patch_llm_router(stub):
    """Return a context manager that injects the stub into the LLM router."""
    return patch.multiple(
        "core.unified.llm_router",
        get_unified_llm_router=lambda: stub,
    )


async def _run_dpr(message: str, source: str = "chat", **kw) -> Dict[str, Any]:
    """Run a fresh DesktopPresenceRuntime with the given message and source."""
    from core.desktop_presence_runtime import DesktopPresenceRuntime
    runtime = DesktopPresenceRuntime()
    kw.setdefault("session_id", "android-nl-test-session")
    kw.setdefault("user_id", "android-nl-test-user")
    result = await runtime.handle_request(
        message=message,
        source=source,
        **kw,
    )
    return result


# ---------------------------------------------------------------------------
# 1. GoalNormalizer boundary contract
# ---------------------------------------------------------------------------


class TestGoalNormalizerBoundaryContract:
    """GoalNormalizer role: structural normalization only, NOT LLM semantic authority."""

    def test_goal_normalizer_role_constant_is_correct(self):
        """GOAL_NORMALIZER_ROLE must describe structural normalization."""
        from core.android_nl_semantic_chain_contract import GOAL_NORMALIZER_ROLE
        assert GOAL_NORMALIZER_ROLE == "android_structural_normalization", (
            "GOAL_NORMALIZER_ROLE must be 'android_structural_normalization' — "
            "GoalNormalizer only converts a raw NL string to NormalizedGoal, "
            "it does NOT perform LLM semantic reasoning."
        )

    def test_goal_normalizer_is_not_semantic_authority(self):
        """GoalNormalizer role must differ from the V2 semantic authority role."""
        from core.android_nl_semantic_chain_contract import (
            GOAL_NORMALIZER_ROLE,
            V2_SEMANTIC_AUTHORITY,
        )
        assert GOAL_NORMALIZER_ROLE != V2_SEMANTIC_AUTHORITY, (
            "GoalNormalizer is a structural normalization component. "
            "It must NOT be conflated with V2_SEMANTIC_AUTHORITY."
        )

    def test_contract_sentinel_present(self):
        """The contract module must export its sentinel constant."""
        from core.android_nl_semantic_chain_contract import (
            ANDROID_NL_SEMANTIC_CHAIN_CONTRACT_SENTINEL,
        )
        assert ANDROID_NL_SEMANTIC_CHAIN_CONTRACT_SENTINEL, (
            "ANDROID_NL_SEMANTIC_CHAIN_CONTRACT_SENTINEL must be a non-empty string "
            "so the contract presence can be machine-verified."
        )

    def test_android_carrier_sources_contains_goal_execution(self):
        """ANDROID_CARRIER_SOURCES must include 'android_goal_execution'."""
        from core.android_nl_semantic_chain_contract import (
            ANDROID_CARRIER_SOURCES,
            ANDROID_NL_CARRIER_SOURCE,
        )
        assert ANDROID_NL_CARRIER_SOURCE in ANDROID_CARRIER_SOURCES, (
            "android_goal_execution must be in ANDROID_CARRIER_SOURCES so "
            "is_android_nl_carrier() returns True for this source tag."
        )

    def test_is_android_nl_carrier_true_for_goal_execution(self):
        """is_android_nl_carrier() must return True for 'android_goal_execution'."""
        from core.android_nl_semantic_chain_contract import is_android_nl_carrier
        assert is_android_nl_carrier("android_goal_execution") is True, (
            "is_android_nl_carrier('android_goal_execution') must be True — "
            "Android cross-device NL uses this source tag."
        )

    def test_is_android_nl_carrier_false_for_chat(self):
        """is_android_nl_carrier() must return False for 'chat'."""
        from core.android_nl_semantic_chain_contract import is_android_nl_carrier
        assert is_android_nl_carrier("chat") is False, (
            "is_android_nl_carrier('chat') must be False — "
            "'chat' is the desktop-direct NL path."
        )


# ---------------------------------------------------------------------------
# 2. LocalPlannerService boundary contract
# ---------------------------------------------------------------------------


class TestLocalPlannerServiceBoundaryContract:
    """LocalPlannerService role: local task decomposition, NOT LLM semantic authority."""

    def test_local_planner_service_role_constant_is_correct(self):
        """LOCAL_PLANNER_SERVICE_ROLE must describe local task decomposition."""
        from core.android_nl_semantic_chain_contract import LOCAL_PLANNER_SERVICE_ROLE
        assert LOCAL_PLANNER_SERVICE_ROLE == "android_local_task_decomposition", (
            "LOCAL_PLANNER_SERVICE_ROLE must be 'android_local_task_decomposition' — "
            "LocalPlannerService decomposes goals into steps locally "
            "(rule-based or device-local model). It does NOT perform "
            "system-level LLM semantic reasoning."
        )

    def test_local_planner_service_is_not_semantic_authority(self):
        """LocalPlannerService role must differ from V2 semantic authority."""
        from core.android_nl_semantic_chain_contract import (
            LOCAL_PLANNER_SERVICE_ROLE,
            V2_SEMANTIC_AUTHORITY,
        )
        assert LOCAL_PLANNER_SERVICE_ROLE != V2_SEMANTIC_AUTHORITY, (
            "LocalPlannerService is a local task decomposition component. "
            "It must NOT be conflated with V2_SEMANTIC_AUTHORITY."
        )

    def test_local_planner_service_path_type_distinct_from_cross_device(self):
        """Android local NL path type must differ from cross-device path type."""
        from core.android_nl_semantic_chain_contract import (
            ANDROID_LOCAL_NL_PATH_TYPE,
            ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
        )
        assert ANDROID_LOCAL_NL_PATH_TYPE != ANDROID_CROSS_DEVICE_NL_PATH_TYPE, (
            "android_local_nl and android_cross_device_nl must be distinct "
            "path type values — the two paths have completely different semantic "
            "processing chains."
        )

    def test_nl_path_types_covers_local_and_cross_device(self):
        """NL_PATH_TYPES must include both Android local and cross-device variants."""
        from core.android_nl_semantic_chain_contract import (
            NL_PATH_TYPES,
            ANDROID_LOCAL_NL_PATH_TYPE,
            ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
            DESKTOP_DIRECT_NL_PATH_TYPE,
        )
        for expected in (
            ANDROID_LOCAL_NL_PATH_TYPE,
            ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
            DESKTOP_DIRECT_NL_PATH_TYPE,
        ):
            assert expected in NL_PATH_TYPES, (
                f"NL_PATH_TYPES must include {expected!r} — all three NL paths "
                f"must be enumerated in the contract."
            )


# ---------------------------------------------------------------------------
# 3. Android cross-device NL → V2 semantic chain e2e
# ---------------------------------------------------------------------------


class TestAndroidCrossDeviceNLToV2SemanticChain:
    """Prove the Android cross-device NL path reaches V2's LLM semantic authority.

    Evidence:
    - source="android_goal_execution" is now a first-class recognized source in DPR.
    - DPR stamps ingress_carrier_context with semantic_authority="v2_openclawd".
    - The full OpenClawd → AgentKernel → LLM stub chain runs.
    """

    def test_android_goal_execution_source_goes_to_openclawd(self):
        """DPR must route android_goal_execution source through OpenClawd."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "打开微信发消息",
                    source="android_goal_execution",
                    device_id="android_test_device_001",
                )
            )

        assert result.get("success") is not False or result.get("response") is not None, (
            "android_goal_execution source must reach OpenClawd and return a result"
        )
        assert result.get("tristate") == "silent", (
            "After android_goal_execution processing, tristate must be 'silent' — "
            "the full DPR lifecycle (SILENT→LIMINAL→MANIFEST→SILENT) must complete."
        )

    def test_ingress_carrier_context_present_for_android_source(self):
        """ingress_carrier_context must be present for android_goal_execution source."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "帮我设置闹钟",
                    source="android_goal_execution",
                    device_id="android_test_device_002",
                )
            )

        assert "ingress_carrier_context" in result, (
            "ingress_carrier_context must be stamped on android_goal_execution results"
        )

    def test_semantic_authority_is_v2_for_android_goal_execution(self):
        """semantic_authority must be 'v2_openclawd' for android_goal_execution source."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "查看天气",
                    source="android_goal_execution",
                    device_id="android_test_device_003",
                )
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("semantic_authority") == "v2_openclawd", (
            "semantic_authority must be 'v2_openclawd' for android_goal_execution — "
            "V2's OpenClawd + AgentKernel + MultiLLMRouter is the sole LLM semantic "
            "authority. Android GoalNormalizer is structural-only."
        )

    def test_carrier_is_android_goal_execution(self):
        """ingress_carrier_context.carrier must be 'android_goal_execution'."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "导航到家",
                    source="android_goal_execution",
                    device_id="android_test_device_004",
                )
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("carrier") == "android_goal_execution", (
            "ingress_carrier_context.carrier must be 'android_goal_execution' — "
            "this identifies Android as the NL source/carrier."
        )

    def test_is_android_carrier_true(self):
        """ingress_carrier_context.is_android_carrier must be True."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "搜索周边餐厅",
                    source="android_goal_execution",
                    device_id="android_test_device_005",
                )
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("is_android_carrier") is True, (
            "is_android_carrier must be True for android_goal_execution source"
        )

    def test_nl_path_type_is_android_cross_device(self):
        """ingress_carrier_context.nl_path_type must be 'android_cross_device_nl'."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "播放音乐",
                    source="android_goal_execution",
                    device_id="android_test_device_006",
                )
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("nl_path_type") == "android_cross_device_nl", (
            "nl_path_type must be 'android_cross_device_nl' for android_goal_execution — "
            "this distinguishes the cross-device path (Android carrier, V2 semantic "
            "authority) from the Android local NL path (no V2 LLM involvement)."
        )

    def test_runtime_session_id_propagated(self):
        """runtime_session_id must be present and non-empty."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(
                    "打开相机",
                    source="android_goal_execution",
                    device_id="android_test_device_007",
                )
            )

        rsid = result.get("runtime_session_id", "")
        assert rsid, (
            "runtime_session_id must be non-empty for android_goal_execution "
            "so the V2 semantic processing can be traced."
        )


# ---------------------------------------------------------------------------
# 4. Desktop direct NL path
# ---------------------------------------------------------------------------


class TestDesktopDirectNLPath:
    """Desktop-direct NL (source='chat') must be tagged as desktop_direct_nl."""

    def test_desktop_nl_has_semantic_authority_v2(self):
        """Desktop NL path must also have semantic_authority='v2_openclawd'."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("帮我截图", source="chat")
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("semantic_authority") == "v2_openclawd", (
            "Desktop NL must also have semantic_authority='v2_openclawd' — "
            "V2 is always the semantic authority regardless of source."
        )

    def test_desktop_nl_path_type_is_desktop_direct(self):
        """Desktop NL must have nl_path_type='desktop_direct_nl'."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("你好", source="chat")
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("nl_path_type") == "desktop_direct_nl", (
            "nl_path_type must be 'desktop_direct_nl' for source='chat' — "
            "this distinguishes desktop users from Android carriers."
        )

    def test_desktop_nl_is_not_android_carrier(self):
        """Desktop NL must have is_android_carrier=False."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("测试", source="chat")
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("is_android_carrier") is False, (
            "is_android_carrier must be False for desktop NL (source='chat')"
        )


# ---------------------------------------------------------------------------
# 5. Semantic authority is always V2 regardless of carrier
# ---------------------------------------------------------------------------


class TestSemanticAuthorityIsAlwaysV2:
    """Prove semantic_authority=='v2_openclawd' for all DPR-processed paths."""

    @pytest.mark.parametrize("source", [
        "chat",
        "android_goal_execution",
        "android_vision",
        "openclawd",
        "operator",
    ])
    def test_semantic_authority_is_v2_for_all_sources(self, source: str):
        """semantic_authority must be 'v2_openclawd' regardless of source."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr(f"test from {source}", source=source)
            )

        ctx = result.get("ingress_carrier_context", {})
        assert ctx.get("semantic_authority") == "v2_openclawd", (
            f"semantic_authority must be 'v2_openclawd' for source={source!r}. "
            f"The source/carrier tag identifies who sent the request; "
            f"the semantic authority is always V2's LLM chain."
        )


# ---------------------------------------------------------------------------
# 6. Contract module assertion helpers (machine-verifiable)
# ---------------------------------------------------------------------------


class TestAndroidNLCarrierVsSemanticAuthorityContracts:
    """Use contract module helpers to machine-verify the semantic chain boundaries."""

    def test_assert_v2_is_semantic_authority_passes_for_android_carrier(self):
        """assert_v2_is_semantic_authority must pass for android_goal_execution results."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("合同断言测试", source="android_goal_execution")
            )

        from core.android_nl_semantic_chain_contract import assert_v2_is_semantic_authority
        # Must not raise
        assert_v2_is_semantic_authority(result, context="android_goal_execution")

    def test_assert_android_nl_carrier_passes_for_android_source(self):
        """assert_android_nl_carrier must pass for android_goal_execution results."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("Android carrier 断言", source="android_goal_execution")
            )

        from core.android_nl_semantic_chain_contract import assert_android_nl_carrier
        # Must not raise
        assert_android_nl_carrier(result, context="android_goal_execution")

    def test_assert_nl_path_type_passes_for_android_cross_device(self):
        """assert_nl_path_type must pass for android_cross_device_nl path type."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("NL path 类型断言", source="android_goal_execution")
            )

        from core.android_nl_semantic_chain_contract import (
            assert_nl_path_type,
            ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
        )
        # Must not raise
        assert_nl_path_type(result, ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
                            context="android_cross_device")

    def test_assert_android_nl_carrier_fails_for_chat_source(self):
        """assert_android_nl_carrier must FAIL for desktop 'chat' source."""
        stub = _make_stub()
        _reset_openclawd_singleton()
        _reset_dpr_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_dpr("桌面直接对话", source="chat")
            )

        from core.android_nl_semantic_chain_contract import assert_android_nl_carrier
        with pytest.raises(AssertionError):
            assert_android_nl_carrier(result, context="chat_should_not_be_android")

    def test_build_android_nl_carrier_context_shape(self):
        """build_android_nl_carrier_context must return a dict with all required fields."""
        from core.android_nl_semantic_chain_contract import (
            build_android_nl_carrier_context,
            ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
            V2_SEMANTIC_AUTHORITY,
            ANDROID_NL_CARRIER_SOURCE,
        )
        ctx = build_android_nl_carrier_context(
            device_id="android_device_x",
            session_id="session_y",
            invocation_id="invocation_z",
        )
        assert ctx["carrier"] == ANDROID_NL_CARRIER_SOURCE
        assert ctx["semantic_authority"] == V2_SEMANTIC_AUTHORITY
        assert ctx["nl_path_type"] == ANDROID_CROSS_DEVICE_NL_PATH_TYPE
        assert ctx["is_android_carrier"] is True
        assert ctx["device_id"] == "android_device_x"


# ---------------------------------------------------------------------------
# 7. goal_execution handler uses correct source tag (code-level contract)
# ---------------------------------------------------------------------------


class TestGoalExecutionHandlerUsesCorrectSource:
    """Prove the goal_execution handler uses source='android_goal_execution', not 'chat'."""

    def test_goal_execution_handler_source_is_android_goal_execution(self):
        """The goal_execution handler must call DPR with source='android_goal_execution'.

        This is the root fix that ensures the carrier is correctly identified
        so ingress_carrier_context.carrier != 'chat' for Android NL requests.
        """
        handler_src = (
            REPO_ROOT / "galaxy_gateway" / "android" / "handlers" / "goal_execution.py"
        ).read_text(encoding="utf-8")
        # Must NOT use source="chat" for the goal_execution → DPR call
        # (the old broken pattern that hid the Android carrier identity).
        assert 'source="android_goal_execution"' in handler_src, (
            "galaxy_gateway/android/handlers/goal_execution.py must call "
            "runtime.handle_request(source='android_goal_execution', ...) — "
            "using source='chat' hides the Android carrier identity and breaks "
            "ingress_carrier_context.carrier discrimination."
        )

    def test_goal_execution_handler_does_not_use_chat_as_source(self):
        """The goal_execution handler must NOT call DPR with source='chat'."""
        handler_src = (
            REPO_ROOT / "galaxy_gateway" / "android" / "handlers" / "goal_execution.py"
        ).read_text(encoding="utf-8")
        # Count occurrences of source="chat" — should be 0 in handle_request calls.
        # (Comments mentioning 'chat' are acceptable; we check for the assignment.)
        import re
        # Find all handle_request calls that use source="chat"
        chat_sources = re.findall(
            r'handle_request\s*\([^)]*source\s*=\s*["\']chat["\']',
            handler_src,
            re.DOTALL,
        )
        assert len(chat_sources) == 0, (
            "goal_execution.py must not use source='chat' in handle_request calls — "
            "this was the bug that mis-labeled Android NL requests as desktop chat. "
            f"Found {len(chat_sources)} occurrence(s)."
        )

    def test_dpr_dispatch_recognizes_android_goal_execution(self):
        """DPR._dispatch must list 'android_goal_execution' as a recognized source.

        Ensures the source is not silently treated as 'unknown' and falls back
        with a warning instead of routing through the canonical OpenClawd path.
        """
        dpr_src = (
            REPO_ROOT / "core" / "desktop_presence_runtime.py"
        ).read_text(encoding="utf-8")
        assert "android_goal_execution" in dpr_src, (
            "core/desktop_presence_runtime.py must recognize 'android_goal_execution' "
            "as a first-class source in _dispatch() so it routes through OpenClawd "
            "without triggering the 'unknown source' warning path."
        )

    def test_dpr_ingress_carrier_context_has_semantic_authority_field(self):
        """DPR must stamp semantic_authority in ingress_carrier_context."""
        dpr_src = (
            REPO_ROOT / "core" / "desktop_presence_runtime.py"
        ).read_text(encoding="utf-8")
        assert "semantic_authority" in dpr_src, (
            "core/desktop_presence_runtime.py must stamp 'semantic_authority' in "
            "ingress_carrier_context so the V2 LLM authority is machine-verifiable "
            "in every DPR result."
        )

    def test_android_nl_semantic_chain_contract_module_exists(self):
        """The Android NL semantic chain contract module must exist."""
        contract_path = REPO_ROOT / "core" / "android_nl_semantic_chain_contract.py"
        assert contract_path.exists(), (
            "core/android_nl_semantic_chain_contract.py must exist — "
            "this module provides machine-verifiable constants and helpers for "
            "the Android NL semantic chain contract."
        )
