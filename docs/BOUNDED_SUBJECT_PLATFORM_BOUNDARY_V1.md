# Bounded Subject Platform Boundary v1

> **适用仓库：** `DannyFish-11/ufo-galaxy-realization-v2`（V2）、`DannyFish-11/ufo-galaxy-android`（Android）  
> **文档性质：** 准平台态边界收束声明。基于前序所有 PR 已真实建立起来的 canonical governance、distributed subject contract、Android bounded subject runtime、participant governance、multi-subject closure、operator governance plane、observability/evidence contract，对最终系统边界做最小必要固化。  
> **PR：** PR-14V2

---

## 1. 准平台态正式定义

本系统已达到**稳定准平台态**（stable quasi-platform state），正式定义为：

> **真实一体化协同的中心治理型多相对主体分布式 AI runtime 系统**
>
> *(Genuinely integrated, canonically-governed, multi-bounded-subject distributed AI runtime system)*

这**不是**宣称系统已经成为 fully mature distributed platform。这是对双仓系统当前真实状态的最小诚实描述。

准平台态成立的条件是以下五个边界轴同时满足：

| # | 边界轴 | 成立条件 |
|---|---|---|
| 1 | **Canonical Center Boundary** | V2 的四个权威域均为 INTACT |
| 2 | **Bounded Subject Boundary** | Android / 参与者的有界约束已声明且不漂移 |
| 3 | **Participant Governance Boundary** | 参与者生命周期状态转换仅由 V2 canonical governance 授权 |
| 4 | **Observability / Evidence Boundary** | 四层可见性分类法已声明，未与 canonical truth 混淆 |
| 5 | **Outward Consumption Boundary** | 所有对外面向层均为纯消费层，不重新拼接 authority |

---

## 2. 五个边界轴详情

### 2.1 Canonical Center Boundary

**定义**：V2 是 canonical governance / truth convergence / dispatch arbitration / closure authority 的唯一中心。

**四个权威域**：

| 权威域 | 代码锚点 |
|---|---|
| COMPLETION_TRUTH | `core/unified_result_ingress.py` (`UnifiedResultIngress`) |
| CONTINUITY_LEGALITY_TRUTH | `core/unified_continuity_legality_authority.py` |
| DISPATCH_READINESS_TRUTH | `core/canonical_dispatch_slot_authority.py` |
| ORCHESTRATION_TRUTH | `core/unified_orchestration_spine.py` |

**CI 断言**：`core.center_authority_boundary.assert_center_authority_intact()`

**禁止**：任何 bounded subject 或外部 runtime 被抬升为平行 canonical center。

---

### 2.2 Bounded Subject Boundary

**定义**：Android（及其他 bounded relative subjects）具有本地 lifecycle、本地 AI system consumption、本地执行判断权与本地可见面，但**不拥有**全局 truth finalization 与全局 dispatch authority。

**代码锚点**：

| 合约 | 代码 |
|---|---|
| 分布式主体合约 v1 | `contracts/distributed_subject_contract_v1.py` |
| Participant lifecycle 由中心授权 | `PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER` |
| Subject evidence 不是 canonical truth | `SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH` |
| Android 真值上行入口 | `core/android_participant_truth_ingress.py` |
| Android SSOT 构建 | `core/v2_android_truth_ssot.py` |
| Android runtime host 角色 | `core/android_runtime_host.py` (`AndroidRuntimeHostRole`) |

**禁止**：Android 或任何参与者被声明为持有全局 truth finalization 或 dispatch authority。

---

### 2.3 Participant Governance Boundary

**定义**：参与者生命周期状态转换仅由 V2 canonical governance 授权发出。Bounded relative subject 可以上报 readiness / posture / busy 信号，但不能单方面晋升或降级自己的参与者生命周期状态。

**代码锚点**：

| 功能 | 代码 |
|---|---|
| Operator action governance | `core/operator_action_governance.py` |
| Execution governance audit | `core/execution_governance_audit_authority.py` |
| Android participant truth ingress | `core/android_participant_truth_ingress.py` |
| Android ↔ V2 truth SSOT | `core/v2_android_truth_ssot.py` |

**禁止**：任何外部 surface 直接修改参与者生命周期状态而不经过 V2 canonical governance。

---

### 2.4 Observability / Diagnostics / Evidence Boundary

**定义**：全系统使用统一的四层可见性分类法与五种 evidence contract kind。可见性边界不构成平行 observability center，也不反向成为 canonical truth 来源。

**四层可见性**：

| 层级 | 约束 |
|---|---|
| `LOCAL_VISIBLE` | 仅在 bounded subject 内部可见；不可未经 uplink 路径直接晋升 |
| `RUNTIME_VISIBLE` | 可见于 V2 runtime 基础设施；只经过声明的 ingress 模块到达 truth 链 |
| `OPERATOR_VISIBLE` | operator dashboard 的只读投影；不可反写 canonical truth |
| `PRODUCT_VISIBLE` | 最外层只读消费面；只消费 canonical / bounded outputs |

**代码锚点**：`core/cross_subject_observability_contract.py`

**禁止**：新造平行 observability center 或 diagnostics authority。

---

### 2.5 Outward Consumption Boundary

**定义**：所有对外面向（outward-facing / product-facing / operator-facing / projection-facing）层均为纯消费层。它们**不得**重新拼接 authority、truth、dispatch 或 closure。它们只能消费 V2 canonical center 生产的 canonical outputs。

**代码锚点**：

| 表面 | 代码 |
|---|---|
| 最终接受面边界 | `core/final_acceptance_surface_boundary.py` |
| Outward runtime truth | `core/outward_runtime_truth.py` |
| Operator route | `core/routes/operator.py` |
| Projection route | `core/routes/projection.py` |
| Unified panel | `core/unified_panel_aggregation.py` |

**禁止**：任何 outward 层被抬升为新的平台主权层或 authority center。

---

## 3. 中心 ↔ 主体 ↔ 对外消费者的最终关系

```
                    ┌─────────────────────────────┐
                    │   V2 Canonical Center        │
                    │   (governance / truth /      │
                    │    dispatch / closure)       │
                    └───────────┬─────────────────┘
                                │ distributes governance &
                                │ accepts evidence uplink
              ┌─────────────────▼─────────────────┐
              │   Bounded Relative Subjects        │
              │   (Android, Desktop Presence,      │
              │    external devices)               │
              │   • local lifecycle                │
              │   • local AI consumption           │
              │   • local execution judgment       │
              │   • local visible surfaces         │
              │   • NO global truth finalization   │
              │   • NO global dispatch authority   │
              └─────────────────┬─────────────────┘
                                │ canonical outputs
              ┌─────────────────▼─────────────────┐
              │   Outward Consumers                │
              │   (operator / product /            │
              │    projection / panel)             │
              │   • consumption only               │
              │   • no authority reassembly        │
              │   • no parallel center claims      │
              └─────────────────────────────────────┘
```

---

## 4. 准平台态 CI 校验

系统通过以下机器可校验的断言来维持准平台态：

| 校验 | 代码 |
|---|---|
| 中心权威域均 INTACT | `core.center_authority_boundary.assert_center_authority_intact()` |
| 准平台态五轴均满足 | `core.bounded_subject_platform_boundary.assert_quasi_platform_state_intact()` |
| 跨主体可见性合约无漂移 | `core.cross_subject_observability_contract.build_cross_subject_observability_snapshot()` |
| 最终接受面边界无重组 | `core.final_acceptance_surface_boundary.build_final_acceptance_surface_boundary()` |

**测试覆盖**：`tests/test_pr14v2_bounded_subject_platform_boundary.py`

---

## 5. 强制约束（永久有效）

1. **不允许** final integration / platform boundary 层重新拼 authority / truth / dispatch / closure。
2. **不允许** 把 Android 或任何 participant 抬升为平行 canonical center。
3. **不允许** 把 outward-facing / product-facing / operator-facing / projection-facing 层抬高为新的平台主权层。
4. **必须明确** 全部五个边界轴，且每轴必须有真实代码锚点。
5. **必须以双仓真实已有主链为基础**，不允许抽象漂移。
6. **必须与前序所有 PR 的系统定义、contract、closure、governance 保持一致**。

---

## 6. Android ↔ V2 叙事一致性

本文档与 Android 仓库的系统边界声明保持一致：

- Android 是 bounded relative subject runtime（非平行 canonical center）
- Android 参与者 truth 上行路径：`GalaxyConnectionService` → `android_participant_truth_ingress` → `v2_android_truth_ssot`
- Android 可见面（diagnostics / runtime-visible / local-visible / product-visible）均在四层可见性分类法下归类
- Android 不持有 operator governance authority
- Android 不持有最终 acceptance / closure 权威

---

## 7. 与前序 PR 的一致性

| PR | 已建立的能力 | 本 PR 如何收束 |
|---|---|---|
| PR-Task1 | 正式系统定义 v1 | 继承系统定义，收束为准平台态定义 |
| PR-Task3 | 分布式主体合约 v1 | Bounded subject boundary 轴的代码锚点 |
| PR-V6 | Center authority boundary | Canonical center boundary 轴的 CI 断言 |
| PR-4 | Operator governance plane | Participant governance boundary 轴 |
| PR-12V2 | Cross-subject observability contract | Observability/evidence boundary 轴 |
| PR-13V2 | Final acceptance surface boundary | Outward consumption boundary 轴 |

---

*本文档由 `core/bounded_subject_platform_boundary.py` 代码约束，由 `tests/test_pr14v2_bounded_subject_platform_boundary.py` 测试锁定。*
