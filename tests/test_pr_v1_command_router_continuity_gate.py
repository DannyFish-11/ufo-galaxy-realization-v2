"""tests/test_pr_v1_command_router_continuity_gate.py
======================================================
PR-V1-DISPATCH:CommandRouter 下发口接入 V1 统一会话连续性合法性权威（Gate C）。

修的是什么
----------
``core.unified_continuity_legality_authority`` 是「会话连续性是否合法」的**唯一**
规范权威，但此前它只守住了**结果回流口**（``galaxy_gateway/android/handlers/
task_lifecycle.py`` 的 ``TERMINAL_RESULT_INGESTION``）。全系统唯一的规范派发口
``CommandRouter.route_envelope()`` **从不询问它**。

后果不是纸面的：一台设备的 runtime attachment 已进入 terminal 态（``replaced`` /
``invalidated``，例如会话被顶替），它依然能被派发新命令；要等命令**真的执行完**、
结果回流时才在回流口被拒 —— 中间那次真实执行已经发生，拒不回来。

Gate C 与 Gate A 不是重复
-------------------------
- Gate A（``source_execution_eligibility``）：这个**来源**有没有执行姿态？
- Gate C（``unified_continuity_legality``）：这个**动作**相对会话连续性合法吗？

一个看能力、一个看身份时效，两者都过才可派发。本文件对两者的独立性也有断言。

覆盖
----
1.  ``CONTINUITY_LEGALITY_REJECTED`` 错误码存在且与 ``V3_SLOT_BLOCKED`` 分开。
2.  route_envelope() 在热路径上**真的调用**了 V1（回归主体：此前调用次数为 0）。
3.  提交的是 ``ONLINE_DISPATCH_ACCEPTANCE`` 路径。
4.  ``REJECT`` → 阻断派发，``_execute_command`` 一次都不执行。
5.  ``REQUIRE_REVIEW`` → 默认**不**阻断（权威没能判定 ≠ 判定为非法）。
6.  ``REQUIRE_REVIEW`` + ``GALAXY_DISPATCH_..._ENFORCEMENT=strict`` → 阻断。
7.  ``ALLOW`` → 正常放行。
8.  权威不可用（抛异常）→ 降级放行且 trace 留痕，不是静默。
9.  envelope.metadata → ContinuityLegalityContext 的字段映射（含 source 优先）。
10. 空身份 envelope 天然放行（V1 对空身份判 ALLOW）。
11. **端到端**：真实权威 + 真实会话注册表里的 terminal 态条目 → 派发被拒。
12. Gate C 在 lifecycle ``mark_running`` **之前**执行（被拒的命令不留 running 记录）。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from core.command_router import (
        DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV,
        DISPATCH_CONTINUITY_LEGALITY_GATE_APPLIED,
        CommandRouter,
        GatewayErrorCode,
    )

    _ROUTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ROUTER_AVAILABLE = False

try:
    from core.unified_continuity_legality_authority import (
        ContinuityLegalityPath,
        ContinuityLegalityReport,
        ContinuityLegalityVerdict,
    )

    _V1_AVAILABLE = True
except ImportError:  # pragma: no cover
    _V1_AVAILABLE = False

try:
    from core.schemas.task_envelope import TaskEnvelope

    _ENVELOPE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ENVELOPE_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _V1_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter / V1 authority / TaskEnvelope unavailable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(metadata: Optional[Dict[str, Any]] = None, targets: Optional[List[str]] = None) -> Any:
    return TaskEnvelope(
        task_id=f"v1gate_{uuid.uuid4().hex[:8]}",
        targets=targets if targets is not None else ["device_alpha"],
        tool_name="test_tool",
        args={},
        metadata=metadata or {},
    )


def _report(verdict: "ContinuityLegalityVerdict", reason: str = "") -> "ContinuityLegalityReport":
    return ContinuityLegalityReport(
        path=ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE,
        verdict=verdict,
        reject_reason=reason,
        dimensions=[],
        context_snapshot={},
    )


def _approving_slots_result(device_ids: List[str]) -> Any:
    """构造一个「全部放行」的 V3 slot 结果。

    为什么需要它：测试环境里 ``device_alpha`` 根本没在 UDM 注册，V3 slot 门会先
    一步把派发拦死。于是「REJECT 之后执行器没被调用」这类断言会**因为下游先拦了**
    而恒真 —— 门被摘掉也照样绿。第一版就踩了这个坑（摘掉 Gate C 后该用例仍通过）。
    把下游放行掉，断言才真正落在 Gate C 身上。
    """
    from core.canonical_dispatch_slot_authority import (
        CanonicalDispatchSlot,
        CanonicalDispatchSlotsResult,
        CanonicalDispatchSlotStatus,
    )

    slots = [
        CanonicalDispatchSlot(
            device_id=d,
            execution_mode="cross_device",
            slot_approved=True,
            status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
            reason="approved for test",
        )
        for d in device_ids
    ]
    return CanonicalDispatchSlotsResult(
        execution_mode="cross_device",
        approved_slots=slots,
        blocked_slots=[],
        can_proceed=True,
        block_reason="",
    )


class _GateHarness:
    """跑一次 route_envelope，并把 V1 的调用参数与派发是否发生记录下来。

    ``_execute_command`` 被替换成计数用的 AsyncMock —— 「是否真的没派发」这条
    断言必须落在**执行有没有被调用**上，只看返回的 error_code 证明不了阻断
    （返回错误但底下已经执行过，正是本 PR 要修的那个形态）。

    ``clear_downstream=True`` 会把 V3 slot 门放行，使这个 envelope 在**没有**
    Gate C 时确实能走到执行 —— 只有这样，「Gate C 拦住了它」才是个有内容的断言。
    """

    def __init__(
        self,
        report: Any = None,
        raises: Optional[Exception] = None,
        clear_downstream: bool = False,
    ) -> None:
        self.report = report
        self.raises = raises
        self.clear_downstream = clear_downstream
        self.v1_calls: List[Dict[str, Any]] = []
        self.execute_mock = AsyncMock(
            return_value={
                "success": True,
                "result": None,
                "error_code": None,
                "error_message": "",
                "latency_ms": 1.0,
            }
        )

    def _fake_evaluate(self, path: Any, ctx: Any, **kwargs: Any) -> Any:
        self.v1_calls.append({"path": path, "ctx": ctx, "kwargs": kwargs})
        if self.raises is not None:
            raise self.raises
        return self.report

    async def run(self, envelope: Any) -> Dict[str, Any]:
        import contextlib

        router = CommandRouter()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch(
                    "core.unified_continuity_legality_authority.evaluate_continuity_legality",
                    side_effect=self._fake_evaluate,
                )
            )
            stack.enter_context(patch.object(router, "_execute_command", self.execute_mock))
            if self.clear_downstream:
                stack.enter_context(
                    patch(
                        "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                        return_value=_approving_slots_result(list(envelope.targets or [])),
                    )
                )
            return await router.route_envelope(envelope)

    @property
    def dispatched(self) -> bool:
        return self.execute_mock.await_count > 0


# ---------------------------------------------------------------------------
# 1 — 错误码
# ---------------------------------------------------------------------------


class TestContinuityLegalityErrorCode:
    def test_error_code_exists(self) -> None:
        assert "CONTINUITY_LEGALITY_REJECTED" in [e.value for e in GatewayErrorCode]

    def test_error_code_is_distinct_from_slot_blocked(self) -> None:
        """刻意与 V3_SLOT_BLOCKED 分开:一个是"没槽位"(可等可重试),
        一个是"身份非法"(必须重建会话)——调用方的处置完全不同。"""
        assert GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value != GatewayErrorCode.V3_SLOT_BLOCKED.value

    def test_gate_sentinel_documents_the_wiring(self) -> None:
        assert "ONLINE_DISPATCH_ACCEPTANCE" in DISPATCH_CONTINUITY_LEGALITY_GATE_APPLIED
        assert "unified_continuity_legality_authority" in DISPATCH_CONTINUITY_LEGALITY_GATE_APPLIED


# ---------------------------------------------------------------------------
# 2/3 — V1 真的被调用，且走的是 ONLINE_DISPATCH_ACCEPTANCE 路径
# ---------------------------------------------------------------------------


class TestV1IsConsultedOnDispatchPath:
    """回归主体:接入之前,这个计数恒为 0。"""

    @pytest.mark.asyncio
    async def test_v1_is_called_at_least_once(self) -> None:
        h = _GateHarness(_report(ContinuityLegalityVerdict.ALLOW))
        await h.run(_make_envelope({"session_id": "s1", "source_device_id": "dev1"}))
        assert h.v1_calls, "CommandRouter.route_envelope() 必须向 V1 提交派发合法性"

    @pytest.mark.asyncio
    async def test_v1_is_called_with_online_dispatch_acceptance_path(self) -> None:
        h = _GateHarness(_report(ContinuityLegalityVerdict.ALLOW))
        await h.run(_make_envelope({"session_id": "s1"}))
        assert h.v1_calls[0]["path"] is ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE


# ---------------------------------------------------------------------------
# 4 — REJECT 阻断
# ---------------------------------------------------------------------------


class TestHardRejectBlocksDispatch:
    @pytest.mark.asyncio
    async def test_reject_returns_structured_error(self) -> None:
        h = _GateHarness(_report(ContinuityLegalityVerdict.REJECT, "attachment session replaced"))
        result = await h.run(_make_envelope({"session_id": "stale", "source_device_id": "dev1"}))
        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        assert "attachment session replaced" in result["error_message"]

    @pytest.mark.asyncio
    async def test_reject_means_execution_never_happens(self) -> None:
        """本条才是"阻断"的实质证明:执行器一次都没被 await。

        必须配 ``clear_downstream=True`` —— 否则 V3 slot 门会先把这个未注册的
        目标拦掉,断言就变成恒真(摘掉 Gate C 也照样绿)。
        """
        h = _GateHarness(_report(ContinuityLegalityVerdict.REJECT, "stale identity"), clear_downstream=True)
        await h.run(_make_envelope({"session_id": "stale", "source_device_id": "dev1"}))
        assert h.dispatched is False, "REJECT 之后不允许发生任何真实执行"

    @pytest.mark.asyncio
    async def test_reject_result_carries_constraint_trace(self) -> None:
        h = _GateHarness(_report(ContinuityLegalityVerdict.REJECT, "stale identity"))
        result = await h.run(_make_envelope({"session_id": "stale"}))
        trace = result.get("_constraint_chain_trace") or {}
        assert trace.get("continuity_legality_applied") is True
        assert trace.get("continuity_legality_blocked") is True
        assert trace.get("continuity_legality_verdict") == "reject"


# ---------------------------------------------------------------------------
# 5/6 — REQUIRE_REVIEW 的两种模式
# ---------------------------------------------------------------------------


class TestRequireReviewIsAdvisoryByDefault:
    """「权威没能判定」和「权威判定为非法」不是一回事。

    在本路径上 REQUIRE_REVIEW 只有一个来源:会话注册表模块导入失败。把"权威自己
    坏了"升级成"全系统一条命令都发不出去"是自伤 —— Gate A / Gate B 在同样处境下
    也都是降级放行。想要更严可显式打开 strict。
    """

    @pytest.mark.asyncio
    async def test_require_review_does_not_block_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv(DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV, raising=False)
        h = _GateHarness(
            _report(ContinuityLegalityVerdict.REQUIRE_REVIEW, "registry unavailable"),
            clear_downstream=True,
        )
        result = await h.run(_make_envelope({"session_id": "s1"}))
        assert result.get("error_code") != GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        assert h.dispatched is True

    @pytest.mark.asyncio
    async def test_require_review_is_still_recorded_in_trace(self, monkeypatch) -> None:
        """不阻断不等于不留痕 —— 否则运维看不到权威退化过。"""
        monkeypatch.delenv(DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV, raising=False)
        h = _GateHarness(_report(ContinuityLegalityVerdict.REQUIRE_REVIEW, "registry unavailable"))
        result = await h.run(_make_envelope({"session_id": "s1"}))
        trace = result.get("_constraint_chain_trace") or {}
        assert trace.get("continuity_legality_verdict") == "require_review"
        assert trace.get("continuity_legality_blocked") is False

    @pytest.mark.asyncio
    async def test_require_review_blocks_under_strict_enforcement(self, monkeypatch) -> None:
        monkeypatch.setenv(DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV, "strict")
        h = _GateHarness(
            _report(ContinuityLegalityVerdict.REQUIRE_REVIEW, "registry unavailable"),
            clear_downstream=True,
        )
        result = await h.run(_make_envelope({"session_id": "s1"}))
        assert result["error_code"] == GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        assert h.dispatched is False


# ---------------------------------------------------------------------------
# 7/8 — ALLOW 与降级
# ---------------------------------------------------------------------------


class TestAllowAndGracefulDegradation:
    @pytest.mark.asyncio
    async def test_allow_reaches_execution(self) -> None:
        """放行要断言"真的走到了执行",而不只是"错误码不是这个" ——
        后者在下游先拦掉时恒真,证明不了 Gate C 放了行。"""
        h = _GateHarness(_report(ContinuityLegalityVerdict.ALLOW), clear_downstream=True)
        result = await h.run(_make_envelope({"session_id": "s1"}))
        assert result.get("error_code") != GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        assert h.dispatched is True, "ALLOW 必须真的放行到执行"

    @pytest.mark.asyncio
    async def test_authority_exception_degrades_open_to_execution(self) -> None:
        h = _GateHarness(raises=RuntimeError("authority exploded"), clear_downstream=True)
        result = await h.run(_make_envelope({"session_id": "s1"}))
        assert result.get("error_code") != GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        assert h.dispatched is True, "权威不可用时必须降级放行,而不是把派发链一起拖死"

    @pytest.mark.asyncio
    async def test_authority_exception_is_visible_in_trace_not_silent(self) -> None:
        """「门没跑」必须能和「门跑了并放行」区分开,否则降级就是掩盖。"""
        h = _GateHarness(raises=RuntimeError("authority exploded"))
        result = await h.run(_make_envelope({"session_id": "s1"}))
        trace = result.get("_constraint_chain_trace") or {}
        assert trace.get("continuity_legality_verdict") == "unavailable"
        assert "authority exploded" in str(trace.get("continuity_legality_reason", ""))
        assert trace.get("continuity_legality_applied") is False


# ---------------------------------------------------------------------------
# 9/10 — 上下文字段映射
# ---------------------------------------------------------------------------


class TestContinuityContextMapping:
    def test_source_device_id_wins_over_device_id(self) -> None:
        """连续性身份问的是**发起方**的会话还算不算数,不是目标设备。"""
        ctx = CommandRouter._build_dispatch_continuity_context(
            _make_envelope({"source_device_id": "origin", "device_id": "target"})
        )
        assert ctx.device_id == "origin"

    def test_session_id_is_accepted_as_runtime_session_id(self) -> None:
        """与 route_envelope 里已有的 V3 slot 门取同一批 metadata 键,
        避免同一个 envelope 在两个门里被认成两个身份。"""
        ctx = CommandRouter._build_dispatch_continuity_context(_make_envelope({"session_id": "s-42"}))
        assert ctx.runtime_session_id == "s-42"

    def test_all_continuity_fields_are_carried(self) -> None:
        ctx = CommandRouter._build_dispatch_continuity_context(
            _make_envelope(
                {
                    "source_device_id": "dev1",
                    "runtime_session_id": "rs1",
                    "runtime_attachment_session_id": "as1",
                    "durable_session_id": "ds1",
                    "continuity_epoch": "7",
                    "contract_id": "c1",
                    "flow_id": "f1",
                }
            )
        )
        assert ctx.device_id == "dev1"
        assert ctx.runtime_session_id == "rs1"
        assert ctx.runtime_attachment_session_id == "as1"
        assert ctx.durable_session_id == "ds1"
        assert ctx.continuity_epoch == 7
        assert ctx.contract_id == "c1"
        assert ctx.flow_id == "f1"

    def test_malformed_epoch_does_not_raise(self) -> None:
        """metadata 是外部可控的;一个坏 epoch 不该把整条派发链炸掉。"""
        ctx = CommandRouter._build_dispatch_continuity_context(_make_envelope({"continuity_epoch": "not-a-number"}))
        assert ctx.continuity_epoch == 0

    def test_empty_metadata_yields_empty_identity(self) -> None:
        ctx = CommandRouter._build_dispatch_continuity_context(_make_envelope({}))
        assert ctx.device_id == ""
        assert ctx.runtime_session_id == ""

    @pytest.mark.asyncio
    async def test_envelope_without_identity_is_allowed_by_real_authority(self) -> None:
        """不打桩,用**真**权威:空身份必须放行。

        否则这个门一上线就会把所有本地/纯工具类 envelope 全拒掉。
        """
        from core.unified_continuity_legality_authority import evaluate_continuity_legality

        report = evaluate_continuity_legality(
            ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE,
            CommandRouter._build_dispatch_continuity_context(_make_envelope({})),
        )
        assert report.verdict is ContinuityLegalityVerdict.ALLOW


# ---------------------------------------------------------------------------
# 11 — 端到端:真实权威 + 真实注册表
# ---------------------------------------------------------------------------


class TestEndToEndWithRealAuthority:
    """打桩只证明了接线,证明不了"这个门真能拦住那个具体的坏情况"。

    这一条走真权威:往会话注册表塞一个 terminal 态条目,断言派发确实被拒 ——
    也就是本 PR 开头描述的那个真实缺陷（会话已被顶替，命令仍被下发）。
    """

    @pytest.mark.asyncio
    async def test_terminal_attachment_state_blocks_dispatch(self) -> None:
        try:
            from core.attached_runtime_session_registry import lookup_session_by_device  # noqa: F401
        except ImportError:  # pragma: no cover
            pytest.skip("attached_runtime_session_registry unavailable")

        terminal_entry = MagicMock()
        terminal_entry.attachment_state = "replaced"
        terminal_entry.runtime_session_id = "rs-old"
        terminal_entry.runtime_attachment_session_id = "as-old"

        router = CommandRouter()
        execute_mock = AsyncMock(return_value={"success": True, "result": None, "error_code": None})
        env = _make_envelope({"source_device_id": "dev-replaced", "runtime_attachment_session_id": "as-old"})

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=terminal_entry,
        ):
            with patch.object(router, "_execute_command", execute_mock):
                with patch(
                    "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                    return_value=_approving_slots_result(list(env.targets or [])),
                ):
                    result = await router.route_envelope(env)

        assert (
            result["error_code"] == GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        ), "runtime attachment 已是 terminal 态('replaced')的设备不得再被派发新命令"
        assert execute_mock.await_count == 0


# ---------------------------------------------------------------------------
# 12 — Gate 顺序
# ---------------------------------------------------------------------------


class TestGateOrdering:
    @pytest.mark.asyncio
    async def test_gate_c_runs_before_lifecycle_mark_running(self) -> None:
        """被拒的命令不该在生命周期里留下一条 running 记录 ——
        否则 orchestrator 会等一个永远不会来的结果。"""
        marked: List[str] = []

        class _FakeLifecycle:
            def mark_running(self, envelope: Any) -> Any:
                marked.append(envelope.task_id)
                return envelope

        h = _GateHarness(_report(ContinuityLegalityVerdict.REJECT, "stale"), clear_downstream=True)
        with patch("core.task_lifecycle.get_lifecycle_manager", return_value=_FakeLifecycle()):
            await h.run(_make_envelope({"session_id": "stale"}))

        assert marked == [], "Gate C 必须在 lifecycle mark_running 之前阻断"

    @pytest.mark.asyncio
    async def test_gate_a_and_gate_c_are_independent(self) -> None:
        """两个门问的是不同问题:Gate A 判定为 eligible 不代表 Gate C 也放行。"""
        h = _GateHarness(_report(ContinuityLegalityVerdict.REJECT, "stale identity"), clear_downstream=True)
        # join_runtime = Gate A 眼里完全合格的来源
        result = await h.run(_make_envelope({"source_runtime_posture": "join_runtime", "source_device_id": "dev1"}))
        assert result["error_code"] == GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
        trace = result.get("_constraint_chain_trace") or {}
        assert trace.get("posture_eligible") is True, "前提:Gate A 确实放行了这个来源"
