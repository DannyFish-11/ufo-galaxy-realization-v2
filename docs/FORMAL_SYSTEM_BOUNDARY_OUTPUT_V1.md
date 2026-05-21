# Formal System Boundary Output v1

> 适用仓库：`DannyFish-11/ufo-galaxy-realization-v2`（V2）、`DannyFish-11/ufo-galaxy-android`（Android）  
> 输出性质：可长期引用的正式 summary / schema / boundary 输出。  
> 约束来源：`core/bounded_subject_platform_boundary.py`、`core/final_acceptance_surface_boundary.py`。

## 1) 系统是什么 / 还不是什么

- **是什么**：V2 canonical center + bounded relative subjects（Android）+ distributed subject contract + multi-subject governance/closure + observability/evidence contract + outward consumption-only surfaces 的稳定准平台态。
- **还不是什么**：fully mature distributed platform。
- **禁止漂移**：
  - Android 不是平行 canonical center。
  - outward-facing/operator-facing/product-facing/projection-facing 层不是新的 authority layer。

## 2) Platform Boundary Summary（五轴）

正式五轴以 `docs/FORMAL_SYSTEM_BOUNDARY_SUMMARY_V1.json` 为机器可读输出，以 `docs/FORMAL_SYSTEM_BOUNDARY_SUMMARY_SCHEMA_V1.json` 为结构约束：

1. `canonical_center_boundary`
2. `bounded_subject_boundary`
3. `participant_governance_boundary`
4. `observability_diagnostics_evidence_boundary`
5. `outward_consumption_boundary`

## 2.1) Canonical Center / Truth / Dispatch / Observability / Outward 边界总览

`docs/FORMAL_SYSTEM_BOUNDARY_SUMMARY_V1.json` 还固定了 `canonical_boundary_summary`：

- `canonical_center_boundary`
- `truth_convergence_boundary`
- `dispatch_governance_closure_boundary`
- `observability_diagnostics_evidence_boundary`
- `outward_consumption_projection_boundary`
- `stable_quasi_platform_state_definition`

该分组用于长期防漂移：明确 V2 是 canonical governance center，而 outward/operator/projection/panel 仅是消费与投影层。

## 3) Outward Contract Summary

Outward contract 只允许消费 canonical outputs，不允许 authority/truth/dispatch/closure 重组。  
运行时锚点来自：

- `core.final_acceptance_surface_boundary.build_final_acceptance_surface_boundary`
- `core.bounded_subject_platform_boundary.build_quasi_platform_runtime_assertion_report`

并通过 `operator_projection_observability_boundary_summary` 固定：

- operator governance plane 是中心侧定义，不是平行主权中心
- projection surface 是 consumption-only
- observability/diagnostics/evidence 是证据契约层，不是 authority center
- outward surfaces 不是 parallel canonical center

## 4) Runtime Assertion / Test Anchors

- `core.center_authority_boundary.assert_center_authority_intact`
- `core.bounded_subject_platform_boundary.assert_quasi_platform_state_intact`
- `core.bounded_subject_platform_boundary.build_quasi_platform_runtime_assertion_report`
- `core.final_acceptance_surface_boundary.build_final_acceptance_surface_boundary`

该输出由 `tests/test_pr19_formal_system_boundary_output.py` 进行机器约束，防止 narrative、boundary naming、authority relation 回摆。
