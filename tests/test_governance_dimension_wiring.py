"""tests/test_governance_dimension_wiring.py
===============================================
回归防护:delegated_flow_post_graduation_governance 的五维探针必须真正接到【真实
子系统对象】并调到【真实存在的方法】。此前探针 import 的 accessor 名压根不存在
(ImportError 被吞 → 对象恒 None → 维度恒"module not importable"),且假想的
has_* 方法在真实对象上也不存在——整套治理探针形同虚设。

本测试验证:
1. 五个 _get_* accessor 都返回【非 None 的真实单例】;
2. 每个真实对象都暴露探针要调用的 has_* 方法,空状态下返回 False(无回归);
3. 有真实回归状态(冲突/隔离/旁路不健康)时 has_* 如实返回 True(检测真的生效)。
"""

from __future__ import annotations

import core.delegated_flow_post_graduation_governance as gov


def test_all_five_accessors_return_real_singletons():
    for name in (
        "_get_truth_ownership",
        "_get_result_convergence",
        "_get_operator_surface",
        "_get_compat_blocking",
        "_get_continuity_coordinator",
    ):
        obj = getattr(gov, name)()
        assert obj is not None, f"{name} 仍返回 None(死 import 未修好)"


def test_probes_call_existing_methods_and_default_no_regression():
    checks = [
        ("_get_truth_ownership", "has_unresolved_contracts"),
        ("_get_result_convergence", "has_quarantined_results"),
        ("_get_operator_surface", "has_visibility_gap"),
        ("_get_compat_blocking", "has_active_bypass"),
        ("_get_continuity_coordinator", "has_replay_contract_gap"),
    ]
    for acc, meth in checks:
        obj = getattr(gov, acc)()
        assert hasattr(obj, meth), f"{type(obj).__name__} 缺 {meth}(探针假想方法未落地)"
        assert getattr(obj, meth)() is False  # 空状态无回归


def test_truth_conflict_is_detected(monkeypatch):
    obj = gov._get_truth_ownership()

    class _Snap:
        decision_counts = {"quarantine_due_to_posture_conflict": 2}

    monkeypatch.setattr(obj, "build_snapshot", lambda: _Snap())
    assert obj.has_unresolved_contracts() is True  # 冲突被真实检测到


def test_convergence_quarantine_is_detected(monkeypatch):
    obj = gov._get_result_convergence()

    class _Snap:
        decision_counts = {"quarantine_result_due_to_flow_mismatch": 1}

    monkeypatch.setattr(obj, "build_snapshot", lambda: _Snap())
    assert obj.has_quarantined_results() is True


def test_compat_unhealthy_bypass_is_detected(monkeypatch):
    obj = gov._get_compat_blocking()

    class _Snap:
        blocking_canonicalization_healthy = False

    monkeypatch.setattr(obj, "snapshot", lambda recent_n=20: _Snap())
    assert obj.has_active_bypass() is True


def test_truth_no_conflict_is_compliant(monkeypatch):
    obj = gov._get_truth_ownership()

    class _Snap:
        decision_counts = {"canonical_path_confirmed": 5}  # 正常决策,非冲突

    monkeypatch.setattr(obj, "build_snapshot", lambda: _Snap())
    assert obj.has_unresolved_contracts() is False  # 正常决策不误报
