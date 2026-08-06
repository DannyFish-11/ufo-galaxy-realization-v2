#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_architecture_status_report.py
=========================================

``tools/architecture/architecture_status_report.py`` 的用例。

本文件原名 ``test_pr14_runtime_introspection.py``,同时盖着 ``core/runtime_introspection.py``
与本模块两边。前者已删 —— 它是对同一批结果字典的**第二套读法**:实测喂进真实的
``route_envelope`` 结果,23 个字段只抽得出 4 个,而那 4 个在同一个结果自带的
``introspection_snapshot`` 手写字典里全都有;反过来手写字典里的 ``execution_path`` /
``failure_is_retryable`` / ``tool_invocation_truth`` / ``repo_mutation_truth`` 它一个
也给不出,其中 ``execution_path`` 还是唯一有真实生产读取方的那个(``command_router``
用它决定要不要记本地执行链)。

它真正的用法是跨三层聚合 ``build_introspection_snapshot(shell, subject_core, substrate)``,
而全仓没有任何一处同时握着这三份结果 —— 每层只把扁平结果返给上层,不留下层的结果
字典。所以那个聚合模式**没有可能的调用方**。详见删除它的那个提交。

随之删掉的还有 ``architecture_status_from_snapshot()``:它唯一的入参类型是
``RuntimeIntrospectionSnapshot``,输入来源没了。``build_architecture_status_report()``
直接吃各层原始 dict,不依赖已删模块,保留 —— 本文件是它仅有的覆盖。
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_runtime_shell_result(
    *,
    source: str = "api",
    trace_id: str = "trace-123",
    auth_role: str = "runtime_shell_authority",
    entry_surface: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a minimal runtime-shell result dict (as produced by DesktopPresenceRuntime)."""
    return {
        "arch_layer_id": "runtime_shell",
        "authority_metadata": {
            "layer_role": auth_role,
            "canonical_module": "core.desktop_presence_runtime",
        },
        "entrypoint_source": source,
        "entry_surface": entry_surface,
        "trace_id": trace_id,
        "runtime_session_id": trace_id,
        "tristate": "active",
        "success": True,
        "introspection_snapshot": {
            "authority_role": auth_role,
            "entry_source": source,
            "trace_id": trace_id,
        },
    }


def _make_subject_core_result(
    *,
    success: bool = True,
    execution_path: str = "local",
    delegation_point: str = "local",
    remote_mode: Optional[str] = None,
    device_id: Optional[str] = None,
    trace_id: str = "trace-123",
    lifecycle_state: str = "succeeded",
    authority_role: str = "subject_decision_authority",
    plan_summary: Optional[Dict] = None,
    cognition_role: str = "embedded_cognition_layer",
) -> Dict[str, Any]:
    """Build a minimal subject-core result dict (as produced by OpenClawd)."""
    _plan_summary = plan_summary or {
        "primary_step_type": "local_manifestation" if not remote_mode else "remote_command",
        "step_types": ["local_manifestation" if not remote_mode else "remote_command"],
        "execution_path": execution_path,
    }
    return {
        "arch_layer_id": "subject_core",
        "success": success,
        "response": "OK",
        "intent": "chat",
        "trace_id": trace_id,
        "execution_path": execution_path,
        "execution_plan_summary": _plan_summary,
        "execution_lifecycle_state": lifecycle_state,
        "metadata": {
            "trace_id": trace_id,
            "authority_role": authority_role,
            "delegation_point": delegation_point,
            "execution_path": execution_path,
            "remote_execution_mode": remote_mode,
            "device_id": device_id,
            "execution_plan_summary": _plan_summary,
            "execution_lifecycle_state": lifecycle_state,
            "kernel_cognition_role": cognition_role,
        },
        "introspection_snapshot": {
            "authority_role": authority_role,
            "delegation_point": delegation_point,
            "execution_mode": remote_mode,
            "execution_path": execution_path,
            "lifecycle_state": lifecycle_state,
            "execution_plan_summary": _plan_summary,
            "device_id": device_id,
            "trace_id": trace_id,
            "success": success,
        },
    }


def _make_substrate_result(
    *,
    success: bool = True,
    remote_mode: Optional[str] = None,
    lifecycle_state: str = "succeeded",
    failure_domain: Optional[str] = None,
    failure_is_retryable: Optional[bool] = None,
    failure_classification: Optional[Dict] = None,
    retry_policy: Optional[Dict] = None,
    fallback_policy: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Build a minimal substrate result dict (as produced by CommandRouter)."""
    result: Dict[str, Any] = {
        "arch_layer_id": "execution_substrate",
        "success": success,
        "execution_substrate_role": "execution_substrate",
        "lifecycle_state": lifecycle_state,
        "introspection_snapshot": {
            "authority_role": "execution_substrate",
            "execution_substrate_role": "execution_substrate",
            "execution_mode": remote_mode,
            "lifecycle_state": lifecycle_state,
            "failure_domain": failure_domain,
            "failure_is_retryable": failure_is_retryable,
            "success": success,
        },
    }
    if remote_mode:
        result["remote_execution_mode"] = remote_mode
    if failure_domain:
        result["failure_domain"] = failure_domain
        result["failure_is_retryable"] = failure_is_retryable
    if failure_classification:
        result["failure_classification"] = failure_classification
    if retry_policy:
        result["retry_policy"] = retry_policy
    if fallback_policy:
        result["fallback_policy"] = fallback_policy
    return result


def _make_orchestration_meta(
    device_ids: Optional[list] = None,
    orchestration_role: str = "orchestration_layer",
) -> Dict[str, Any]:
    return {
        "arch_layer_id": "orchestration_layer",
        "orchestration_role": orchestration_role,
        "device_ids": device_ids or ["device-1", "device-2"],
    }


# ---------------------------------------------------------------------------
# A) RuntimeIntrospectionSnapshot
# ---------------------------------------------------------------------------


class TestArchitectureStatusReport(unittest.TestCase):
    """I) ArchitectureStatusReport data contract."""

    def setUp(self):
        from tools.architecture.architecture_status_report import ArchitectureStatusReport

        self.cls = ArchitectureStatusReport

    def test_default_construction(self):
        rpt = self.cls()
        self.assertIsNone(rpt.authority_chain_valid)
        self.assertIsNone(rpt.overall_valid)
        self.assertIsInstance(rpt.authority_chain_summary, list)
        self.assertIsInstance(rpt.diagnostics_findings, list)
        self.assertIsInstance(rpt.notes, list)

    def test_to_dict_returns_dict(self):
        rpt = self.cls()
        d = rpt.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_is_json_safe(self):
        rpt = self.cls()
        d = rpt.to_dict()
        json.dumps(d)  # must not raise

    def test_to_dict_contains_expected_keys(self):
        rpt = self.cls()
        d = rpt.to_dict()
        for k in [
            "authority_chain_present",
            "authority_chain_valid",
            "authority_chain_summary",
            "remote_execution_coherent",
            "substrate_distinct_from_orchestration",
            "diagnostics_findings",
            "overall_valid",
            "notes",
            "raw_diagnostics_report",
        ]:
            self.assertIn(k, d, f"Missing key: {k}")

    def test_repr_smoke(self):
        rpt = self.cls(overall_valid=True)
        r = repr(rpt)
        self.assertIsInstance(r, str)


# ---------------------------------------------------------------------------
# J) build_architecture_status_report — authority chain
# ---------------------------------------------------------------------------


class TestBuildArchitectureStatusReport(unittest.TestCase):
    """J) build_architecture_status_report — authority chain checks."""

    def setUp(self):
        from tools.architecture.architecture_status_report import build_architecture_status_report

        self.build = build_architecture_status_report

    def _all_layers(self):
        return dict(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )

    def test_all_four_layers_present_authority_chain_present_true(self):
        rpt = self.build(**self._all_layers())
        self.assertTrue(rpt.authority_chain_present)

    def test_missing_runtime_shell_authority_chain_present_false(self):
        rpt = self.build(
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        self.assertFalse(rpt.authority_chain_present)

    def test_missing_runtime_shell_adds_note(self):
        rpt = self.build(
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        self.assertTrue(any("runtime_shell" in n for n in rpt.notes))

    def test_missing_subject_core_authority_chain_present_false(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            substrate_result=_make_substrate_result(),
        )
        self.assertFalse(rpt.authority_chain_present)

    def test_missing_substrate_authority_chain_present_false(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
        )
        self.assertFalse(rpt.authority_chain_present)

    def test_authority_chain_summary_has_correct_structure(self):
        rpt = self.build(**self._all_layers())
        self.assertIsInstance(rpt.authority_chain_summary, list)
        for entry in rpt.authority_chain_summary:
            self.assertIn("layer", entry)
            self.assertIn("expected_role", entry)
            self.assertIn("present", entry)

    def test_authority_chain_summary_contains_expected_roles(self):
        rpt = self.build(**self._all_layers())
        roles = {e["expected_role"] for e in rpt.authority_chain_summary}
        self.assertIn("runtime_shell_authority", roles)
        self.assertIn("subject_decision_authority", roles)
        self.assertIn("execution_substrate", roles)


# ---------------------------------------------------------------------------
# K) build_architecture_status_report — diagnostics integration
# ---------------------------------------------------------------------------


class TestArchitectureStatusReportDiagnostics(unittest.TestCase):
    """K) diagnostics integration in architecture status report."""

    def setUp(self):
        from tools.architecture.architecture_status_report import build_architecture_status_report

        self.build = build_architecture_status_report

    def test_with_valid_layers_overall_valid_is_not_none(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        # overall_valid should be set (True or False, but not None when layers present)
        self.assertIsNotNone(rpt.overall_valid)

    def test_diagnostics_findings_is_list(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
        )
        self.assertIsInstance(rpt.diagnostics_findings, list)

    def test_raw_diagnostics_report_has_overall_valid(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        if rpt.raw_diagnostics_report is not None:
            self.assertIn("overall_valid", rpt.raw_diagnostics_report)

    def test_no_layers_diagnostics_gracefully_absent(self):
        rpt = self.build()
        # With no layers, chain is absent and diagnostics skipped gracefully
        self.assertFalse(rpt.authority_chain_present)


# ---------------------------------------------------------------------------
# L) architecture_status_from_snapshot
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 已删除的用例组
# ---------------------------------------------------------------------------
# A~H  测 core/runtime_introspection.py —— 该模块已删,理由见本文件开头。
# L    测 architecture_status_from_snapshot() —— 随之删除,入参类型没了。
# S    "introspection_snapshot 字段在层结果上" —— 它只断言**本文件自己的 fixture**
#      里有这个键(``_make_runtime_shell_result()`` 就是这里造的),没有碰任何生产
#      代码,是条自证的空测试,一并删掉而不是留着充数。真正钉住该字段的是
#      tests/integration/runtime/test_runtime_integration.py 里的
#      test_introspection_snapshot_present / test_introspection_snapshot_carries_mode,
#      它们跑的是真实的 route_envelope。

if __name__ == "__main__":
    unittest.main()
