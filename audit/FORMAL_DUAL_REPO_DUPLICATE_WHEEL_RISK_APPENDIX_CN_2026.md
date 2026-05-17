# 双仓重复造轮子风险附录（V2 + Android，中文）

> 本附录只记录“多套相似实现并存、后续极易重复建设”的高风险区。  
> 主文引用位置：`audit/FORMAL_DUAL_REPO_MAINLINE_UNINTEGRATED_RISK_BASELINE_CN_2026.md`

---

## 1. 多套状态表达并存

| 风险区 | 现有实现 | 重叠点 | 更接近主线 | 仅应视为派生 / 旁路 / 遗留 | 推荐统一落点 |
| --- | --- | --- | --- | --- | --- |
| 主体状态 vs 协议状态 vs UI 状态 | `core/desktop_presence_runtime.py::TriState`、`core/openclawd.py::tri_state_phase`、`core/current_state_backbone_audit.py::ClosureState`、`system_integration/state_machine_ui_integration.py::SystemState`、`core/v2_unified_mode_model.py` | 都在描述“状态” | `TriState` | `tri_state_phase`、`ClosureState`、`DORMANT/ISLAND/SIDESHEET/FULLAGENT`、mode model | `core/desktop_presence_runtime.py::TriState` |

**最容易重复建设的方式**：后续修状态语义时再新增一个“统一三态”或“超级阶段模型”。  
**应该做的事**：坚持 `TriState` 是主体三态唯一权威，其它一律降格说明。

## 2. 多套任务 / 编排 / 执行路径并存

| 风险区 | 现有实现 | 重叠点 | 更接近主线 | 旁路 / 可选 / 次级链 | 推荐统一落点 |
| --- | --- | --- | --- | --- | --- |
| per-request 执行主链 | `core/openclawd.py` → `core/command_router.py` → `galaxy_gateway/device_router.py` | 都会触发 dispatch / execution | 这条是真主链 | 无 | 继续维持真主链 |
| multi-step / multi-device orchestration | `core/unified_orchestration_spine.py`、`core/swarm_coordinator.py` | 都在管理复杂会话与多设备 | 二者都接近主线，但不是 per-request 主链 | 不应新造第 3 套 orchestration hub | 先厘清 spine vs swarm coordinator 边界 |
| worker-domain control plane | `core/master_brain.py`、`core/nats_bus.py` | 也会 dispatch task | 不是 Android ↔ V2 主链 | worker-domain optional path | 保持为可选 worker-domain |
| bring-up / startup orchestration | `core/system_orchestrator.py` | 名字也叫 orchestrator | 仅负责 startup phase | 不能冒充运行时任务编排层 | 维持 startup role |

## 3. 多套 device truth / capability truth 并存

| 风险区 | 现有实现 | 重叠点 | 更接近主线 | 派生 / 遗留 | 推荐统一落点 |
| --- | --- | --- | --- | --- | --- |
| device state | `core/unified/device_manager.py`、`core/device_registry.py`、`core/device_pool_manager.py`、`core/device_status_api.py` | 都记录 device 信息 | `core/unified/device_manager.py` | 其余应继续视为 compatibility / indexing / scheduling layers | `core/unified/device_manager.py` |
| capability state | `core/agent/capability_registry.py`、`core/unified/capability_resolver.py`、`core/capability_manager.py` | 都在注册 / 读取 capability | registry + resolver | `core/capability_manager.py` 只是 compat bridge | `CapabilityRegistry` + `CapabilityResolver` |

## 4. 多套 operator / status / projection surface 并存

| 风险区 | 现有实现 | 重叠点 | 更接近主线 | 派生 / 旁路 | 推荐统一落点 |
| --- | --- | --- | --- | --- | --- |
| operator truth surface | `core/operator_surface.py` | operator 可见真相 | 更接近主线 | 无 | `core/operator_surface.py` |
| runtime truth / board payload | `core/routes/projection.py` | board / desktop / runtime truth | 主线读模型 | 不是写权威 | `core/routes/projection.py` |
| panel aggregation | `core/unified_panel_aggregation.py` | 聚合很多同类信息 | 次主线读侧聚合 | 不能绕开 projection / operator 自建真相 | 以 operator + projection 为上游 |
| status board UI | `windows_client/status_board_v2/device_surface.py` | 展示同类 runtime truth | 只读表面 | 不是 truth source | 严格只读消费 |
| operator-console shell | `static/operator-console/index.html` | 也是观察面 | 只是壳层 | 不是 truth source | 继续消费 canonical projections |

## 5. 多套 transport 相关机制并存

| 风险区 | 现有实现 | 重叠点 | 更接近主线 | 派生 / overlay / fallback / optional | 推荐统一落点 |
| --- | --- | --- | --- | --- | --- |
| Android ↔ V2 transport | WebSocket ingress + device router | 承担默认双仓 transport | WS | 无 | `galaxy_gateway/routes/websocket.py` + `device_router.py` |
| overlay transport | `core/mesh_coordinator.py` | 也可送消息 | 不是主线 | overlay | 继续保持 subordinate |
| fallback transport | relay / ws fallback | 也可承载消息 | 不是主线 | fallback | 继续保持 fallback 语义 |
| worker-domain fabric | `core/nats_bus.py`、`core/master_brain.py` | 也可 dispatch / result | 不是 Android ↔ V2 主链 | optional | 继续明确为可选 worker-domain |
| Android side direct path | `TailscaleAdapter.kt`、WebRTC signaling files | 也涉及 direct path | 尚未纳入默认治理 | weak link / not fully absorbed | 吸收前先明确不是默认主链 |

## 6. Android 吸收链文件过多

| 风险区 | 现有实现 | 重叠点 | 更接近主线 | 风险 | 推荐统一落点 |
| --- | --- | --- | --- | --- | --- |
| Android ingress / reducer / lifecycle / evidence | `core/android_runtime_transition_reducer.py`、`core/android_participant_truth_ingress.py`、`core/android_execution_signal_reconciler.py`、`core/android_delegated_runtime_lifecycle_coordinator.py`、`core/android_runtime_host.py`、`core/android_network_participation.py` 等 `core/android_*.py` | 都在吸收 Android runtime truth | 尚无单文件能替代全部 | 最容易继续横向增殖 | 以 `UnifiedResultIngress` / `task_result_truth_chain` / `routes/projection` 为统一消费落点 |

---

## 7. 结论

重复造轮子风险最高的，不是“代码空白区”，而是**已经有很多实现但边界仍不够硬的区域**。  
后续修复前最应该先统一的是：

1. 状态唯一权威落点；
2. per-request 主链与 multi-step orchestration 边界；
3. device / capability 写权威；
4. operator / projection 的唯一消费落点；
5. transport 的主链 / overlay / fallback / optional 分层。
