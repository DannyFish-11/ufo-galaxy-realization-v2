"""tests/test_pr_v10_ownership_truth_wiring.py
==============================================
PR-V10-OWNERSHIP：Android 参与者真相入口算出来的**归属**必须送进规范真相链，
而不是算完就丢。

修的是什么
----------
``core/android_participant_truth_ingress.py`` 每次入口都实打实调
``_build_ownership_context()`` 算一份 ``ownership_context``（``ownership_status`` /
``authority_scope`` / ``participant_identity_divergence`` …），此前**没有任何代码把它
往下游送**。

下游并不是不存在。``core/canonical_session_truth.py`` 里有一道完整的准入门
（``CanonicalSessionTruthRuntime.record()``），文档写死：

    Only records with ``participant_ownership_boundary='canonicalized'``
    [enter] the canonical ring buffer.

非 canonicalized 的记录不进环形缓冲，只作为非规范证据写审计存储。这道门实现完整、
判定也对，唯独**永远拿不到非空输入** —— 因此从未生效过一次。

实测（跑真实入口，不打桩）
--------------------------
接通前::

    调用前 规范会话真相记录数 = 0
    入口产出 ownership_context: 是          ← 真的算了
    调用后 规范会话真相记录数 = 0            ← 一条也没进去

接通后（``truth_kind='result'``，未对账成功 → 归属被判 ``rejected_non_canonical``）::

    调用前: 记录数=0  被拦下=0
    调用后: 记录数=0  被拦下=1              ← 门首次真正生效

``core/canonical_ownership_truth_bridge.py`` 正是缺的那截中间件（docstring 自述
"Ownership from Ingress to Truth Continuity Main Chain"），而全仓零处 import 过它。

两个刻意的取舍
--------------
* **只在终态种类上调用**。环形缓冲虽有界（``deque(maxlen=…)``），每个入口事件都写一条
  仍会把有价值的终态记录挤掉。终态集合复用入口里既有的 ``_TERMINAL_TRUTH_KINDS``。
* **不按 ``was_reconciled`` 过滤**。非规范归属恰恰多出现在未成功对账的情形；若按它
  过滤，门就还是只能看到本来就合规的记录 —— 等于仍未生效。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest

try:
    from core.android_participant_truth_ingress import (
        _TERMINAL_TRUTH_KINDS,
        ingest_android_participant_truth_message,
    )
    from core.canonical_session_truth import get_canonical_session_truth_runtime

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="truth ingress / canonical session truth unavailable")


def _runtime() -> Any:
    return get_canonical_session_truth_runtime()


def _counts() -> tuple:
    rt = _runtime()
    return len(getattr(rt, "_records", [])), int(getattr(rt, "_non_canonical_rejected_count", 0))


def _outcome(status: str) -> SimpleNamespace:
    """构造一个只带归属上下文的 outcome —— 桥的公开入参形状。"""
    return SimpleNamespace(
        ownership_context={
            "ownership_status": status,
            "authority_scope": (
                "v2_canonical_orchestration" if status == "canonicalized" else "android_participant_local"
            ),
            "participant_identity": "pr_v10_dev",
            "truth_kind": "result",
        },
        envelope=SimpleNamespace(session_id="pr_v10_sess", trace_id="pr_v10_trace"),
        was_reconciled=(status == "canonicalized"),
    )


class TestAdmissionGateActuallyWorks:
    """先证明"要接的东西没坏"：准入门本身判得对。"""

    def test_canonicalized_ownership_is_admitted(self) -> None:
        """合规归属必须真的进入规范环形缓冲。

        判据看**内容**不看条数。第一版断言 ``after_n == before_n + 1``，在整分片跑动
        时必挂：环形缓冲是 ``deque(maxlen=128)``，一旦被前面的用例灌满，再写入时旧记录
        被挤出、**条数不再增长**（已实测：128 → 128）。那条断言等于要求「缓冲永不满」，
        与它自己的容量语义直接冲突 —— 是用例写错了，不是产品的问题。
        """
        from core.canonical_ownership_truth_bridge import record_participant_truth_with_ownership

        marker = "pr_v10_admitted_marker"
        record_participant_truth_with_ownership(_outcome("canonicalized"), task_id=marker, truth_source="result")

        records = list(_runtime()._records)
        assert records, "合规归属必须进入规范环形缓冲 —— 否则等于把所有记录都拦掉了"
        mine = [r for r in records if getattr(r, "task_id", None) == marker]
        assert mine, f"没找到本用例刚写入的记录（task_id={marker!r}）—— 合规归属没有被收下"
        assert mine[-1].participant_ownership_boundary == "canonicalized"

    @pytest.mark.parametrize(
        "status",
        ["participant_local_only", "fallback_non_canonical", "rejected_non_canonical"],
    )
    def test_non_canonical_ownership_is_blocked(self, status: str) -> None:
        """反向用例：非规范归属必须被拦，不能因为接通了就一律放行。"""
        from core.canonical_ownership_truth_bridge import record_participant_truth_with_ownership

        marker = f"pr_v10_blocked_{status}"
        _, before_b = _counts()
        record_participant_truth_with_ownership(_outcome(status), task_id=marker, truth_source="result")
        _, after_b = _counts()

        # 同样看内容不看条数（环形缓冲满了之后条数不变，见上一条用例的说明）。
        assert not [
            r for r in _runtime()._records if getattr(r, "task_id", None) == marker
        ], f"{status} 不得进入规范环形缓冲"
        assert after_b == before_b + 1, f"{status} 必须被准入门计入拦截 —— 否则它是被静默丢弃而不是被判定"


class TestIngressFeedsTheGate:
    """红 → 绿的主体：活入口必须把归属送到门口。"""

    def test_terminal_ingress_reaches_the_admission_gate(self) -> None:
        before_n, before_b = _counts()
        msg: Dict[str, Any] = {
            "truth_kind": "result",
            "device_id": "pr_v10_ingress_dev",
            "session_id": "pr_v10_ingress_sess",
            "task_id": "pr_v10_ingress_task",
            "payload": {
                "task_id": "pr_v10_ingress_task",
                "session_id": "pr_v10_ingress_sess",
                "success": True,
                "result": "ok",
            },
        }
        out = ingest_android_participant_truth_message(msg)

        assert (out.ownership_context or {}).get("ownership_status"), "前提：入口本来就会算出 ownership_status"

        after_n, after_b = _counts()
        assert (after_n, after_b) != (before_n, before_b), (
            "终态入口必须把归属送进规范真相链 —— 要么被准入门收下、要么被它拦下并计数；"
            "两者都没发生说明这份每次都在算的归属又被丢掉了"
        )

    def test_result_kind_is_in_the_terminal_set(self) -> None:
        """钉住上面那条用的种类确实落在触发集合里，避免它悄悄变成无效用例。"""
        assert "result" in _TERMINAL_TRUTH_KINDS

    def test_ingress_survives_a_broken_bridge(self) -> None:
        """真相记录是可观测面：桥坏掉不得让参与者真相入口整体失败。"""
        import core.canonical_ownership_truth_bridge as bridge_mod

        original = bridge_mod.record_participant_truth_with_ownership

        def _boom(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("simulated bridge failure")

        bridge_mod.record_participant_truth_with_ownership = _boom  # type: ignore[assignment]
        try:
            out = ingest_android_participant_truth_message(
                {
                    "truth_kind": "result",
                    "device_id": "pr_v10_degraded",
                    "session_id": "pr_v10_degraded_sess",
                    "task_id": "pr_v10_degraded_task",
                    "payload": {"task_id": "pr_v10_degraded_task", "success": True},
                }
            )
            assert out is not None, "桥抛异常时入口必须照常返回 outcome"
            assert out.ownership_context, "降级路径上归属上下文仍应正常产出"
        finally:
            bridge_mod.record_participant_truth_with_ownership = original  # type: ignore[assignment]


class TestIngressDelegatesToTheBridge:
    """源码级判据：入口必须经桥消费归属，不能又自己重造一套。"""

    @staticmethod
    def _src() -> str:
        import pathlib

        return (
            pathlib.Path(__file__).resolve().parent.parent / "core" / "android_participant_truth_ingress.py"
        ).read_text(encoding="utf-8")

    def test_ingress_imports_the_ownership_bridge(self) -> None:
        assert "canonical_ownership_truth_bridge" in self._src(), "入口必须经 PR-4V2 归属桥把归属送进规范真相链"

    def test_ingress_calls_the_bridge_entry_point(self) -> None:
        """判据是"走桥的接点"，不是"调某个具体函数名"。

        接点刻意选 ``bridge_participant_outcome_if_terminal`` 而不是直接调
        ``record_participant_truth_with_ownership``：终态判断与降级包装放在桥里，
        入口只留一处调用 —— 该入口文件在 File Complexity Budget 上早已超标（基线
        1887 行），不该为了这次接入再被推高二十几行。
        """
        assert "bridge_participant_outcome_if_terminal" in self._src()
