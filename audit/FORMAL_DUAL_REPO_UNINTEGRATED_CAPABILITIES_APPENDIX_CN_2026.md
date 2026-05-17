# 双仓未一体化能力附录（V2 + Android，中文）

> 本附录只记录“代码已经存在，但尚未真正吸纳进统一主链或统一治理消费”的能力。  
> 主文引用位置：`audit/FORMAL_DUAL_REPO_MAINLINE_UNINTEGRATED_RISK_BASELINE_CN_2026.md`

---

## 1. 多步编排治理能力已存在，但没有统一覆盖所有入口

| 能力 | 代码位置 | 当前使用方式 | 为什么还没真正一体化 | 不先吸纳会怎样重复造轮子 |
| --- | --- | --- | --- | --- |
| multi-step orchestration spine | `core/unified_orchestration_spine.py` | 只治理 `PARALLEL_FANOUT / DELEGATED_RUNTIME / HANDOFF / TAKEOVER / CROSS_DEVICE / HYBRID` | 文件自身已写明“V4 is NOT the universal synchronous per-request gate” | 后续极易再造一个“统一调度层”去覆盖 per-request |
| multi-device orchestration layer | `core/swarm_coordinator.py` | 位于 `OpenClawd` 之上，用于 multi-device plan / dispatch_team | 它是 orchestration layer，不是 substrate root | 后续多设备修复很容易再造一套 Team/Plan/Dispatch 桥 |

## 2. Android 强运行时状态已存在，但 V2 还没完全对称吸收

| 能力 | 代码位置 | 当前使用方式 | 为什么还没真正一体化 | 风险 |
| --- | --- | --- | --- | --- |
| Android execution mode authority | `app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt` | 明确声明自己是 single, machine-verifiable authority | `core/v2_unified_state_contract.py` 明写 “Android symmetry is not yet guaranteed by V2 alone” | V2 侧继续再造 transition reducer / synthetic mode state |
| Android runtime continuity / takeover / degraded recovery | `app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt` | 管理 takeoverFailure、continuity epoch、recovery | V2 侧读路径多，写回与对称消费未完全统一 | 再造新的 session / continuity / takeover status 层 |
| Android delegated execution / goal / parallel runtime | `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`、`app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt` | 消费 `task_assign / goal_execution / parallel_subtask` | V2 聚合侧仍以 projection / contract / audit 方式吸收，不是单一统一 runtime SSOT | 后续再造“Android 执行状态聚合器” |

## 3. transport 能力远比默认主链更丰富，但还未统一进入策略层

| 能力 | 代码位置 | 当前使用方式 | 为什么还没真正一体化 | 风险 |
| --- | --- | --- | --- | --- |
| Direct WS / relay / mesh role hierarchy | `core/transport_hierarchy.py`、`core/mesh_coordinator.py` | 已区分 `primary / fallback / overlay` | 真实消费策略仍分散在 dispatch / mesh / Android runtime / gateway | 后续再造“统一网络层”时误把 overlay 当主链 |
| NATS worker-domain transport | `core/nats_bus.py`、`core/master_brain.py` | opt-in、`GALAXY_MASTER_BRAIN_ENABLED`、`GALAXY_NATS_URL`，且 NATS 连接失败可 local-only 退化 | 不属于当前 Android ↔ V2 默认主链 | 后续修 transport 时误把 NATS 升为默认主链 |
| Android direct / mesh-side transport | Android `TailscaleAdapter.kt`、`WebRTCSignalingClient.kt`、`IceCandidateManager.kt`、`TurnConfig.kt` | Android 侧已有 direct path / signaling 能力 | V2 主链仍以 WS ingress 为主 | 后续做 P2P/mesh 时绕开现有 Android transport 能力重造 |

## 4. 观察面 / 面板 / 壳层能力已存在，但还没有单一统一产品壳

| 能力 | 代码位置 | 当前使用方式 | 为什么还没真正一体化 | 风险 |
| --- | --- | --- | --- | --- |
| operator read surface | `core/operator_surface.py`、`core/routes/operator.py` | canonical operator-visible projection | 偏 read-only governance surface | 后续再造 operator state store |
| unified panel aggregation | `core/unified_panel_aggregation.py` | 聚合 operator / Android ecosystem / shell / readiness | 仍与 runtime-truth / board / desktop projection 并行 | 再造新的 panel aggregation |
| runtime truth payload | `core/routes/projection.py`、`windows_client/status_board_v2/device_surface.py` | board / status board consumption | 是 projection read model，不是产品壳 | 后续桌面壳层再次自己拼状态 |
| desktop projection shell fragments | `desktop_projection/liminal_space_engine.py`、`desktop_projection/manifest_stage_controller.py`、`static/operator-console/index.html` | 有 liminal / manifest stage / operator-console 壳 | 没有形成统一完整 desktop shell | 再造新的 shell 状态与动画系统 |

## 5. 多模态能力已存在双路径，但仍未统一成单一真值面

| 能力 | 代码位置 | 当前使用方式 | 为什么还没真正一体化 | 风险 |
| --- | --- | --- | --- | --- |
| continuous host perception | `core/multimodal/ingress_bus.py` | `DesktopPresenceRuntime` shell 持续感知总线 | 属于 shell 连续感知层 | 再造新的 ambient perception state |
| request-bound multimodal fusion | `core/perception/multimodal_bus.py`、`core/openclawd.py` | `multimodal_context` 的每请求融合 | 属于 core 请求级融合 | 再造新的 request multimodal fusion pipeline |

## 6. 设备与能力 SSOT 已存在，但旧层仍大量保留

| 能力 | 代码位置 | 当前使用方式 | 为什么还没真正一体化 | 风险 |
| --- | --- | --- | --- | --- |
| 设备写入唯一权威 | `core/unified/device_manager.py` | UDM device state authority | `core/device_registry.py`、`core/device_pool_manager.py`、`core/device_status_api.py` 仍存在 | 再造平行 device truth |
| 能力写 / 读权威 | `core/agent/capability_registry.py`、`core/unified/capability_resolver.py` | canonical writer + preferred reader | `core/capability_manager.py` 仍作为 compat bridge 保留 | 再造 capability registry / resolver |

---

## 7. 结论

这些未一体化能力的共同特点不是“没有代码”，而是：

1. **已经存在真实实现**；
2. **部分被主链消费，但没有形成唯一统一落点**；
3. **如果修复前不先冻结边界，最容易导致重复建设。**
