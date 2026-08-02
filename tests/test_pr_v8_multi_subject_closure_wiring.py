"""tests/test_pr_v8_multi_subject_closure_wiring.py
====================================================
PR-V8-CLOSURE：多主体执行的对外终态必须出自闭合机，
而不是把 bridge 的一个字符串直接抄到结果上。

修的是什么
----------
``core/multi_subject_closure_machine.py``（PR-8）的模块 docstring 把它的角色写死了：

    3. Provides the single ``ClosureCandidate`` output type that
       operator / projection / **outward-facing layers MUST consume** instead of
       reconstructing closure decisions ad-hoc.

而全仓**零处**真正 import 过它。与此同时两条活路径都在做它禁止的事 ——
直接摘 bridge 的 ``closure.completion_state``：

    # galaxy_gateway/cross_device_coordinator.py:570
    result["completion_state"] = _truth_bridge.get("closure", {}).get("completion_state", "unknown")

    # galaxy_gateway/device_router.py:1953
    _completion_state = _truth_bridge.get("closure", {}).get("completion_state")

``ClosureCandidate`` 有 13 个字段（含 ``reconcile_required`` /
``reconcile_triggers`` / ``is_terminal`` / 五类计数），活路径**只取一个字符串**。

实测差异（``build_closure_candidate`` 的文档化入参就是 bridge 快照）
--------------------------------------------------------------------
=================================  ==================  =============================================
场景                                活路径对外报的       闭合机的判定
=================================  ==================  =============================================
参与者全 lost，无接管候选            ``failed``          ``participant_lost`` + 需协调
                                                       （``participant_lost_no_takeover``）
failed 但存在 degraded 参与者        ``failed``          ``failed`` + 需协调
                                                       （``ambiguous_failure_degraded_present``）
编队声明了成员但快照里 0 个参与者     ``failed``          ``failed`` + 需协调
                                                       （``empty_formation_divergence``）
全成功（反向对照）                    ``success``         ``success``，不需协调
=================================  ==================  =============================================

第一行最要命：**终态种类都不同**。「全体参与者失联」被对外报成「执行失败」——
这两件事的处置完全相反（失联要等待/触发接管，失败是重试或放弃）。
后两行则是「需要协调才能封板」的信号被整条丢弃，上游看到的是一个已封板的终态。

顺带说明一个**不是**缺陷的地方：bridge 自己也算了一个 ``reconcile_required``
并放进 closure 字典，但活路径连它都没读（全仓零消费）。本 PR 不是去读那个字段，
而是按 docstring 的要求改为消费 ``ClosureCandidate`` —— 闭合机的判定比 bridge
那个布尔更完整（它还能给出终态种类与具体触发器）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

try:
    from core.multi_subject_closure_machine import (
        ClosureTerminalKind,
        ReconcileRequiredTrigger,
        build_closure_candidate,
    )

    _MACHINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MACHINE_AVAILABLE = False

try:
    from core.multi_subject_truth_convergence_bridge import build_multi_subject_truth_bridge

    _BRIDGE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _BRIDGE_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not (_MACHINE_AVAILABLE and _BRIDGE_AVAILABLE),
    reason="closure machine / truth convergence bridge unavailable",
)


# ---------------------------------------------------------------------------
# Helpers —— 手工构造 bridge 快照
# ---------------------------------------------------------------------------
#
# 为什么手工构造而不是跑真 bridge：``build_multi_subject_truth_bridge()`` 会查活的
# 设备注册表，未注册的设备一律被 ``orchestration_eligible is False`` 判成 suspended
# （实测：连"全成功"场景都会塌成 suspended）。那样根本构造不出差异化的参与者状态。
# ``build_closure_candidate()`` 的文档化入参本来就是 bridge 快照字典，直接喂它是
# 正当用法；而快照的键形由下面 test_snapshot_shape_matches_real_bridge 用**真**
# bridge 输出锁住，避免手工快照与真实产物漂移。


def _participant(device_id: str, state: str, **kw: Any) -> Dict[str, Any]:
    base = {
        "device_id": device_id,
        "role": "assistant",
        "state": state,
        "formation_role": "support_device",
        "is_source": False,
        "is_recovery": False,
    }
    base.update(kw)
    return base


def _snapshot(
    participants: List[Dict[str, Any]],
    completion_state: str,
    *,
    takeover: Optional[str] = None,
) -> Dict[str, Any]:
    counts = {k: sum(1 for p in participants if p["state"] == k) for k in ("degraded", "lost", "failed", "suspended")}
    counts["success"] = sum(1 for p in participants if p["state"] == "ready")
    return {
        "participants": participants,
        "counts": counts,
        "closure": {
            "completion_state": completion_state,
            "terminal": True,
            "requires_review": completion_state != "success",
            "reconcile_required": False,
            "canonical_truth_status": "converged",
        },
        "failure_isolation": {"takeover_candidate": takeover},
    }


# ---------------------------------------------------------------------------
# 1 — 闭合机本身判得对（先证明"要接的东西没坏"）
# ---------------------------------------------------------------------------


class TestClosureMachineItselfIsCorrect:
    def test_all_lost_without_takeover_is_participant_lost_not_failed(self) -> None:
        """终态种类必须区分「全体失联」与「执行失败」——处置完全不同。"""
        c = build_closure_candidate(_snapshot([_participant("d0", "lost"), _participant("d1", "lost")], "failed"))
        assert c.terminal_kind is ClosureTerminalKind.participant_lost
        assert c.reconcile_required is True
        assert ReconcileRequiredTrigger.participant_lost_no_takeover.value in c.reconcile_triggers

    def test_failed_with_degraded_present_is_ambiguous(self) -> None:
        c = build_closure_candidate(_snapshot([_participant("d0", "failed"), _participant("d1", "degraded")], "failed"))
        assert c.reconcile_required is True
        assert ReconcileRequiredTrigger.ambiguous_failure_degraded_present.value in c.reconcile_triggers

    def test_formation_declared_members_but_no_participants(self) -> None:
        c = build_closure_candidate(_snapshot([], "failed"), formation_member_count=3)
        assert c.reconcile_required is True
        assert ReconcileRequiredTrigger.empty_formation_divergence.value in c.reconcile_triggers

    def test_all_success_needs_no_reconciliation(self) -> None:
        """反向用例：不能为了抓歧义把正常路径也判成需协调。"""
        c = build_closure_candidate(_snapshot([_participant("d0", "ready"), _participant("d1", "ready")], "success"))
        assert c.terminal_kind is ClosureTerminalKind.success
        assert c.reconcile_required is False
        assert c.reconcile_triggers == []

    def test_snapshot_shape_matches_real_bridge(self) -> None:
        """锁住手工快照与**真** bridge 输出的键形一致 —— 防止两者漂移后本文件
        的其余用例变成自说自话。"""
        real = build_multi_subject_truth_bridge(
            formation={"group_id": "g", "members": [{"device_id": "d0"}]},
            participant_results=[{"device_id": "d0", "success": True}],
            source_device_id="src",
        )
        for key in ("participants", "counts", "closure", "failure_isolation"):
            assert key in real, f"闭合机依赖 bridge 快照的 {key!r} 键"
        assert "completion_state" in real["closure"]


# ---------------------------------------------------------------------------
# 2 — 活路径必须消费 ClosureCandidate（红 → 绿的主体）
# ---------------------------------------------------------------------------


class TestOutwardResultCarriesClosureCandidate:
    """docstring 的原话：对外层 MUST 消费 ClosureCandidate，不得自行重构闭合判定。

    判据落在**结果字典里有没有那些字段**上 —— 这是可机器判定的形式。
    """

    @staticmethod
    def _apply(result: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
        from galaxy_gateway.multi_subject_closure_surface import attach_closure_candidate

        return attach_closure_candidate(result, snapshot)

    def test_participant_lost_is_not_flattened_to_failed(self) -> None:
        out = self._apply({}, _snapshot([_participant("d0", "lost"), _participant("d1", "lost")], "failed"))
        assert out["completion_state"] == ClosureTerminalKind.participant_lost.value, (
            "全体参与者失联不得对外报成 'failed' —— 两者的处置完全不同；" f"实际 {out.get('completion_state')!r}"
        )

    def test_reconcile_signal_reaches_the_outward_result(self) -> None:
        out = self._apply({}, _snapshot([_participant("d0", "failed"), _participant("d1", "degraded")], "failed"))
        assert out.get("reconcile_required") is True
        assert ReconcileRequiredTrigger.ambiguous_failure_degraded_present.value in (
            out.get("reconcile_triggers") or []
        )

    def test_full_candidate_is_attached_for_review(self) -> None:
        out = self._apply({}, _snapshot([_participant("d0", "ready")], "success"))
        candidate = out.get("closure_candidate")
        assert isinstance(candidate, dict), "完整 ClosureCandidate 必须随结果对外，供 operator/projection 复核"
        for field in ("terminal_kind", "is_terminal", "reconcile_required", "reconcile_triggers"):
            assert field in candidate, f"closure_candidate 缺字段 {field}"

    def test_success_path_is_unchanged(self) -> None:
        """反向用例：正常成功的对外语义不能被这次接入改掉。"""
        out = self._apply({}, _snapshot([_participant("d0", "ready"), _participant("d1", "ready")], "success"))
        assert out["completion_state"] == "success"
        assert out.get("reconcile_required") is False

    def test_degrades_gracefully_without_a_snapshot(self) -> None:
        """bridge 不可用时（既有代码里它是 try/except 包着的）不得炸掉派发结果。"""
        out = self._apply({"success": True}, {})
        assert out["success"] is True
        assert out.get("completion_state") in (None, "unknown")


# ---------------------------------------------------------------------------
# 3 — 两条活路径都接上了（不能只接一条）
# ---------------------------------------------------------------------------


class TestBothLivePathsUseTheSurface:
    """cross_device_coordinator 与 device_router 是同一个缺陷的两个现场。

    判据用源码级断言：两处都必须走统一入口，且不得再出现直接摘
    ``closure.completion_state`` 的写法 —— 否则修了一条另一条继续漂。
    """

    @staticmethod
    def _src(rel: str) -> str:
        import pathlib

        return (pathlib.Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "path",
        ["galaxy_gateway/cross_device_coordinator.py", "galaxy_gateway/device_router.py"],
    )
    def test_live_path_uses_the_closure_surface(self, path: str) -> None:
        """判据是「走统一出口」，不是「用哪一个函数」。

        surface 有两个入口，两处各按自己的组装时机选：
        ``attach_closure_candidate`` 就地并进已有 result（cross_device_coordinator），
        ``build_closure_view`` 先取值再组装（device_router 要用 completion_state
        决定 message 文案，必须在构造 _result 之前拿到）。
        """
        src = self._src(path)
        assert "multi_subject_closure_surface" in src, f"{path} 必须经统一闭合面消费 ClosureCandidate"
        assert (
            "attach_closure_candidate" in src or "build_closure_view" in src
        ), f"{path} 引入了闭合面但没有调用它的任一入口"

    @pytest.mark.parametrize(
        "path",
        ["galaxy_gateway/cross_device_coordinator.py", "galaxy_gateway/device_router.py"],
    )
    def test_no_raw_completion_state_extraction_remains(self, path: str) -> None:
        src = self._src(path)
        assert 'get("closure", {}).get("completion_state"' not in src, (
            f"{path} 仍在直接摘 bridge 的 completion_state —— "
            "这正是 closure machine docstring 禁止的 ad-hoc 重构闭合判定"
        )
