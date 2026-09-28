# 未接线与不可达代码：到底是些什么东西（2026-09-28）

> 所有者的要求：**先确认清楚是些什么东西，再决定删还是接。** 本文只做清点。
> 本轮没有因为这份清单删掉或接上任何一行代码 —— 下文「随本轮任务顺带处理的」一节列出的，
> 是别的任务（会话迁移、配置写入合并）本来就要动、顺手接上的，每一处都写明了。
>
> 复测命令：
> - `python scripts/unwired_inventory.py --write` —— 刷新本文末尾的生成段（分类表 + 逐文件清单）
> - `python scripts/check_wiring.py --all` —— 原始名单（判据写在该脚本的模块说明里）
> - `python scripts/check_reachability.py --list` —— 从真实入口不可达的模块

## 1. 这 755 条是什么

**判据**（`scripts/check_wiring.py`）：`core/`、`galaxy_gateway/`、`nodes/`、`launcher/` 下名字不以 `_` 开头的
函数/方法，在全仓**除 `tests/` 以外**找不到任何按名字的引用，也不在豁免清单里。

所以它不是「755 个没接上的功能」，而是 **755 个没有生产调用方的公开函数/方法**：

| 事实 | 数 |
|---|---|
| 类方法 / 模块函数 | 486 / 269 |
| 分布在多少个文件 | 359 |
| 只有测试在引用（写了、测了、没接） | 500 |
| 全仓连测试都没引用 | 255 |
| 所在模块本身从入口不可达 | 4（都在下面三个不可达模块里） |

按**名字表明的角色**分（脚本用前缀/后缀做的初筛，不是逐条人工判定）：

| 角色 | 条数 | 这类没人调用意味着什么 |
|---|---|---|
| 动作/变更（record/set/register/route/send/persist…） | 335 | **该动作从没在生产里发生过**。最可能是「能力写了没生效」 |
| 只读查询（get/list/…_snapshot/…_summary） | 129 | 对象的查询面没人读；通常无害，但有时说明对应的观测面没做 |
| 计算/构造（build/derive/decide/normalize…） | 112 | 算法写了没用上；有的已被别的实现取代 |
| 判定谓词（is_/has_/can_/requires_…） | 106 | 同上 |
| 测试复位钩子（reset_/clear_/…_for_testing） | 34 | 基本都是给测试用的，本就不该有生产调用方 |
| 序列化/转换（to_/from_/as_） | 27 | 对象 API 面，无害 |
| 事件回调（on_*） | 12 | **回调写了但没挂到任何事件源上** —— 事件发生时它不会被叫 |

真正意味着「某项能力没生效」的，主要是**动作/变更 + 事件回调这 347 条**；其中连测试都没有的 159 条
（152 + 7）最像真死代码。其余四类多是对象的 API 面。

## 2. 值得先看的几簇 —— 「看得见，但不生效」

这几簇的共同点：**对外有读取面，写入/触发端却没接**。读的人看到的是「一切正常」，其实是「没人记」。

1. **运行 SLO 指标只接了一半。** `core/operational_slo_metrics.py` 的 13 个 `record_*`（派发尝试/成功/失败、
   路由拒绝、回退触发、五种恢复结果、启动恢复扫描、审计落盘成败）全部零生产调用方；但 `/metrics`、
   `core/routes/monitoring.py` 的 JSON 指标端点、`core/routes/projection.py` 都在读它的 snapshot。
   结果：这些计数在生产里**恒为 0**。唯一接上的写入是 `openclawd` 里的 `ingest_latency_budget_summary`。
2. **委托流持久化只接了读。** `core/delegated_flow_persistence.py` 的 `persist_all` 与 8 个
   `persist_*`/`restore_*` 零生产调用方；`core/delegated_flow_recovery_coordinator.py` 却在
   `_has_durable_persistence()` 里读 `flow_entity_store` 判断「有没有持久化检查点」。没人写 → 永远读不到
   → 重启后「从检查点恢复」这条分支在生产里不会走到。
3. **会话漫游的一半生命周期没接。** `galaxy_gateway/session_roaming.py` 的 `close_session`、
   `load_snapshot`、`update_task_state` 零调用方；`auto_migrate_on_attention_shift` 只有测试引用。
   （本轮会话迁移规范面接上了迁移那一部分，`set_migration_callback` 也接上了，见第 4 节。）
4. **配置服务的写入口。** `core/config_service.py` 的 `set_provider_api_key`、`set_oneapi`、`set_network_url`、
   `set_toggle`、`set_native_mm_policy`、`set_android_inference_mode` 生产零调用方 —— 面板保存走的是
   `POST /api/config` → `.env` 那一条，两条写路径没合。（本轮「面板配置写入合并」处理，见第 4 节。）
5. **设备注册表的分组与标签。** `core/device_registry.py` 的 `add_tag`/`remove_tag`/`add_to_group`/
   `remove_from_group` 零调用方、连测试都没有。
6. **事件回调没挂上。** 例如 `UnifiedConfig.on_change`、`ConnectionManager.on_connected`/`on_disconnected`、
   `NodeDiscoveryService.on_node_joined`/`on_node_updated`、`DeviceCommunication.on_device_message`：
   注册回调的入口存在，但没有任何生产代码去注册。

## 3. 三个从真实入口不可达的模块（共 1733 行）

「不可达」＝ 从顶层启动器、网关 app、OpenClawd、API 路由、`nodes/` 等真实入口出发，沿 import 边走不到
（`scripts/check_reachability.py`；**测试不是入口**）。

| 模块 | 行数 | 它是什么（取自它自己的说明） | 谁提到了它 | 为什么说它不生效 |
|---|---|---|---|---|
| `core.local_agent_runtime` | 423 | **端侧** Agent 执行沙盒：收 `AgentManifest`，在本地跑 ReAct / 顺序 / 自主三种循环，逐步回报 | 4 个测试；`orchestration_authority/legacy_paths.py` 把它登记为 `LEGACY_COMPATIBILITY`；`runtime_invariant_enforcement` 的 INV-008 与几处注释 | 设计上它跑在设备端，而设备端是安卓 App（另一仓，Kotlin）；本仓服务端按 PR-S5 明令不得用它做规划。本仓没有任何进程加载它 |
| `core.posture_contract_canonicalization` | 331 | `source_runtime_posture` 字段的契约校验层：规范化、边界断言、从 payload 取 posture，外加 5 个策略哨兵 | `core/runtime/__init__.py` 惰性再导出表里的**字符串**；3 个模块文档字符串里的「PR-1」 | 全仓没有任何生产代码取用它导出的任何一个名字 —— 校验层存在，但 posture 的产生/写入处没有调用它 |
| `core.truth_conflict_enforcement` | 979 | 设备/任务/会话三个真相面的写权威登记 + 写顺序守卫（`assert_canonical_write_precedes_compat_write` 等）+ 健康快照 | `compat_fallback_authority_guard`、`runtime_invariant_enforcement` 在**描述字符串**里提到它；1 个测试文件 | 没有任何写入点调用这些守卫 —— 它声称的「兼容写之前必先写规范源」在运行时从未被检查过 |

## 4. 随本轮任务顺带处理的

本轮别的任务本来就要动下面这些地方，顺手接上；除此之外清单里的条目**一条都没动**。

- 会话迁移规范面（D3）：漫游会话现在经规范面 `core/session_migration.py` 迁移；`core/event_bridge.py` 原先挂错了
  属性，现在经 `SessionRoamingManager.set_migration_callback` 挂上迁移回调 —— 这一条因此从清单里出去了。
- 面板配置写入合并：复核后没有做「合并」（生效的只有一条写入链路），`ConfigService` 那几个写方法**没动**，
  仍在清单里。见 `docs/PANEL_SURFACE_CONVERGENCE.md` 最后一节。

`config/wiring_baseline.json` 已重记（760 → 755）：基线里有 4 条（`current_runtime_session`、`forget`、
`handle_capability_gap`、`is_verified`）早已有了生产调用方，是过期条目；另 1 条是上面接上的 `set_migration_callback`。

## 5. 可选处置（等所有者定，本轮未执行）

| 对象 | 选项 | 我的建议 |
|---|---|---|
| 「看得见但不生效」的几簇（第 2 节 1、2） | 接上写入端 / 撤掉读取面 | **接**。读取面已经对外，恒为 0 或恒读不到比没有更误导 |
| `core.local_agent_runtime` | 删 / 保留 | **删**（连同 `legacy_paths.py` 的登记与 4 个测试）。设备端不是 Python，服务端又明令不用 |
| `core.posture_contract_canonicalization` | 接到 posture 写入处 / 删 | 先看 posture 实际在哪几处产生；只有一两处就接，否则删 |
| `core.truth_conflict_enforcement` | 接到真相写入点 / 删 / 冻结 | 接线要改 UDM / CanonicalTask / 会话真相的**热路径**，风险最高；倾向删或明确标为冻结 |
| 无测试的动作类与事件回调（159 条） | 逐条删 / 接 | 逐条过，多数应删 |
| 有测试、无调用方的动作类（188 条） | 逐条删 / 接 | 逐条过；先看是否已被别的实现取代 |
| 查询、谓词、序列化、复位钩子（408 条） | 豁免 / 保持在基线 | 保持在基线即可；复位钩子可整类加进 `check_wiring.py` 的豁免 |

<!-- BEGIN GENERATED: scripts/unwired_inventory.py --write -->

未接线公开能力 **755** 条，分布在 **359** 个文件。

| 维度 | 数 |
|---|---|
| 类方法 / 模块函数 | 486 / 269 |
| 只有测试在引用（写了、测了、没接） | 500 |
| 全仓连测试都没引用 | 255 |
| 所在模块本身从入口不可达 | 4 |

### 按名字表明的角色

| 角色 | 合计 | 其中只有测试引用 | 其中连测试都没有 |
|---|---|---|---|
| 测试复位钩子 | 34 | 28 | 6 |
| 序列化/转换 | 27 | 14 | 13 |
| 事件回调 | 12 | 5 | 7 |
| 判定谓词 | 106 | 86 | 20 |
| 只读查询 | 129 | 96 | 33 |
| 计算/构造 | 112 | 88 | 24 |
| 动作/变更 | 335 | 183 | 152 |

### 按子系统

| 子系统 | 条数 | 文件数 |
|---|---|---|
| `core/（其余单文件）` | 271 | 134 |
| `galaxy_gateway/` | 53 | 27 |
| `core/capability_*` | 25 | 9 |
| `core/device_*` | 25 | 10 |
| `core/node_*` | 23 | 8 |
| `core/android_*` | 20 | 13 |
| `core/delegated_*` | 20 | 5 |
| `core/cognitive/` | 19 | 8 |
| `core/unified/` | 19 | 8 |
| `core/mesh/` | 18 | 8 |
| `core/orchestration/` | 18 | 7 |
| `core/ugcp_*` | 15 | 3 |
| `nodes/Node_71_MultiDeviceCoordination/` | 15 | 7 |
| `core/task_*` | 11 | 6 |
| `core/attached_runtime_*` | 10 | 5 |
| `core/hybrid_*` | 10 | 2 |
| `core/model_topology/` | 10 | 5 |
| `core/desktop_*` | 9 | 3 |
| `core/canonical_*` | 8 | 3 |
| `core/runtime/` | 8 | 3 |
| `core/v2_*` | 8 | 2 |
| `core/control_plane/` | 7 | 5 |
| `core/cross_*` | 7 | 3 |
| `core/execution_observability/` | 7 | 4 |
| `core/continuation_*` | 6 | 1 |
| `core/flow_*` | 6 | 1 |
| `core/truth_*` | 6 | 3 |
| `launcher/` | 6 | 5 |
| `core/governance/` | 5 | 2 |
| `core/runtime_*` | 5 | 3 |
| `core/adapters/` | 4 | 3 |
| `core/nodes/` | 4 | 1 |
| `nodes/Node_70_AutonomousLearning/` | 4 | 1 |
| `core/agentic/` | 3 | 1 |
| `core/continuum/` | 3 | 2 |
| `core/device_formation/` | 3 | 2 |
| `core/multimodal/` | 3 | 1 |
| `core/perception/` | 3 | 2 |
| `core/presence/` | 3 | 2 |
| `core/resilience/` | 3 | 2 |
| `core/session_*` | 3 | 2 |
| `nodes/Node_112_SelfHealing/` | 3 | 1 |
| `nodes/Node_116_ExternalToolWrapper/` | 3 | 1 |
| `nodes/Node_43_MAVLink/` | 3 | 1 |
| `core/agent/` | 2 | 2 |
| `core/capability_runtime/` | 2 | 2 |
| `core/cross_device_policy/` | 2 | 1 |
| `core/tts/` | 2 | 1 |
| `nodes/Node_05_Auth/` | 2 | 1 |
| `nodes/Node_109_ProactiveSensing/` | 2 | 1 |
| `nodes/Node_54_SymbolicMath/` | 2 | 1 |
| `nodes/Node_72_KnowledgeBase/` | 2 | 1 |
| `core/audit_layer/` | 1 | 1 |
| `core/capabilities/` | 1 | 1 |
| `core/execution/` | 1 | 1 |
| `core/execution_*` | 1 | 1 |
| `core/generative_ui/` | 1 | 1 |
| `core/interaction/` | 1 | 1 |
| `core/operator_*` | 1 | 1 |
| `core/orchestration*` | 1 | 1 |
| `core/output/` | 1 | 1 |
| `core/persona/` | 1 | 1 |
| `core/queueing/` | 1 | 1 |
| `core/reliability_contract/` | 1 | 1 |
| `core/routing_explanation/` | 1 | 1 |
| `nodes/Node_04_Router/` | 1 | 1 |
| `nodes/Node_106_GitHubFlow/` | 1 | 1 |
| `nodes/Node_108_MetaCognition/` | 1 | 1 |
| `nodes/Node_110_SmartOrchestrator/` | 1 | 1 |
| `nodes/Node_127_BambuLab/` | 1 | 1 |
| `nodes/Node_14_FFmpeg/` | 1 | 1 |
| `nodes/Node_33_ADB/` | 1 | 1 |
| `nodes/Node_50_Transformer/` | 1 | 1 |
| `nodes/Node_58_ModelRouter/` | 1 | 1 |
| `nodes/Node_74_DigitalTwin/` | 1 | 1 |
| `nodes/Node_89_APIGateway/` | 1 | 1 |

### 从真实入口不可达的模块

| 模块 | 行数 |
|---|---|
| `core.local_agent_runtime` | 423 |
| `core.posture_contract_canonicalization` | 331 |
| `core.truth_conflict_enforcement` | 979 |

### 逐文件清单

标记：`M` 类方法（后跟所属类）、`F` 模块函数；`T` 只有测试在引用；`—` 连测试都没有。

<details><summary><code>core/（其余单文件）</code> — 271 条</summary>

- `core/acl.py`（2）：`M AntiCorruptionLayer.validate_mcp_call` — · 动作/变更；`M AntiCorruptionLayer.validate_worker_registration` — · 动作/变更
- `core/agent_factory.py`（1）：`M AgentMessageBus.notify_ack` — · 动作/变更
- `core/agent_identity_memory.py`（3）：`M AgentIdentityMemory.add_goal` — · 动作/变更；`M AgentIdentityMemory.remove_goal` — · 动作/变更；`M AgentIdentityMemory.add_value` — · 动作/变更
- `core/agent_manifest.py`（1）：`M AgentManifest.create_multi_step_agent` T · 计算/构造
- `core/agent_team.py`（3）：`M AgentTeam.couple_member` — · 动作/变更；`M AgentTeam.decouple_member` — · 动作/变更；`M TeamManager.list_teams` — · 只读查询
- `core/ai_intent.py`（2）：`M SemanticSearch.initialize_qdrant` — · 动作/变更；`M SemanticSearch.index_document_vector` — · 动作/变更
- `core/aip_transport.py`（4）：`M AIPTransport.transport_stats` — · 只读查询；`M AIPTransport.unregister_adapter` — · 动作/变更；`M AIPTransport.probe_best_transport` — · 动作/变更；`F register_transport_adapter` — · 动作/变更
- `core/ascii_art.py`（1）：`F print_galaxy` — · 计算/构造
- `core/audit_event_semantics.py`（3）：`F audit_route_decision` T · 动作/变更；`F audit_policy_decision` T · 动作/变更；`F audit_failure_domain` T · 动作/变更
- `core/authority_conflict_elimination.py`（1）：`F assert_no_competing_authority` T · 动作/变更
- `core/bounded_subject_platform_boundary.py`（1）：`F assert_quasi_platform_state_intact` T · 动作/变更
- `core/cache.py`（2）：`M CacheManager.cache_node_status` — · 动作/变更；`M CacheManager.cache_session` — · 动作/变更
- `core/channel_plugins.py`（2）：`M ConsoleChannelAdapter.inject` T · 动作/变更；`M ChannelPluginLoader.unload_plugin` — · 动作/变更
- `core/command_router.py`（1）：`M CommandRouter.normalize_legacy_ingress` T · 计算/构造
- `core/compat_fallback_authority_guard.py`（3）：`F assert_canonical_is_decision_authority` T · 动作/变更；`F build_authority_hardening_snapshot` T · 只读查询；`F block_compat_influence_at_decision_site` T · 计算/构造
- `core/compat_legacy_path_blocking_canonicalization.py`（1）：`M CompatLegacyBlockingRecord.is_quarantined` T · 判定谓词
- `core/compute_scheduler.py`（4）：`M ModelAllocation.is_offloaded` — · 判定谓词；`M ComputeScheduler.is_monitoring` — · 判定谓词；`M ComputeScheduler.loaded_model_count` — · 只读查询；`M ComputeScheduler.estimate_quantized_size` — · 计算/构造
- `core/concurrency_manager.py`（4）：`M LockManager.release_all` T · 动作/变更；`M ConcurrencyManager.track_task` — · 动作/变更；`M ConcurrencyManager.run_with_concurrency` T · 动作/变更；`M ConcurrencyManager.run_with_lock` T · 动作/变更
- `core/config_hot_reload.py`（1）：`M HotReloadConfigManager.save_to_file` T · 动作/变更
- `core/config_preflight.py`（1）：`F require_env` T · 计算/构造
- `core/config_service.py`（8）：`M ConfigService.set_provider_api_key` T · 动作/变更；`M ConfigService.set_oneapi` T · 动作/变更；`M ConfigService.set_toggle` T · 动作/变更；`M ConfigService.set_native_mm_policy` T · 动作/变更；`M ConfigService.set_network_url` T · 动作/变更；`M ConfigService.set_android_inference_mode` T · 动作/变更；`M ConfigService.describe_missing` T · 只读查询；`M ConfigService.is_provider_ready` T · 判定谓词
- `core/config_store.py`（1）：`M ConfigStore.write_secrets` T · 动作/变更
- `core/connection_manager.py`（2）：`M ConnectionManager.on_connected` — · 事件回调；`M ConnectionManager.on_disconnected` — · 事件回调
- `core/constellation_runtime.py`（1）：`F warn_legacy_path` T · 动作/变更
- `core/container_runtime.py`（2）：`F set_runtime_choice` — · 动作/变更；`F test_runtime` — · 动作/变更
- `core/conversation_continuity_truth.py`（1）：`M ConversationContinuityClass.is_terminal_loss` T · 判定谓词
- `core/critical_path_harness.py`（3）：`F record_ingress_path` T · 动作/变更；`F record_execution_dispatch` T · 动作/变更；`F snapshot_critical_path` T · 只读查询
- `core/dag_evolver.py`（1）：`M DAGEvolver.on_missing_capability` T · 事件回调
- `core/decision_diff_telemetry.py`（2）：`F clear_diff_store` T · 测试复位钩子；`F record_candidate_diff` T · 动作/变更
- `core/decision_timeline.py`（1）：`F record_source_switch_event` T · 动作/变更
- `core/degraded_operation_envelope.py`（1）：`F envelope_summary` T · 只读查询
- `core/digital_twin_engine.py`（6）：`M DigitalTwin.push_to_physical` — · 动作/变更；`M DigitalTwin.register_physics_model` — · 只读查询；`M DigitalTwinEngine.couple_all` — · 动作/变更；`M DigitalTwinEngine.decouple_all` — · 动作/变更；`F drone_flight_model` — · 只读查询；`F printer_3d_model` — · 只读查询
- `core/duplex_presence_bridge.py`（1）：`M DuplexPresenceBridge.presence_handle` T · 只读查询
- `core/e2e_orchestrator.py`（2）：`F run_multi_device_via_task_graph` T · 动作/变更；`F process_user_input` T · 动作/变更
- `core/error_framework.py`（2）：`M ErrorTracker.is_error_spike` — · 判定谓词；`F error_boundary` — · 动作/变更
- `core/failure_domains.py`（1）：`F map_to_pr_b_domain` T · 计算/构造
- `core/fast_loop.py`（1）：`F active_loop_name` T · 只读查询
- `core/feedback_loop.py`（2）：`M FeedbackLoop.record_user_evaluation` — · 动作/变更；`M FeedbackLoop.should_use_local` — · 判定谓词
- `core/focus_stack.py`（1）：`M FocusStack.drop_current` T · 动作/变更
- `core/full_system_baseline_v3.py`（1）：`M V3BaselineReport.blocking_subsystems` T · 只读查询
- `core/fusion_entry_adapter.py`（1）：`F check_fusion_entry_compliance` T · 动作/变更
- `core/galaxy_main_loop_l4_enhanced.py`（1）：`M GalaxyMainLoopL4.receive_goal` T · 动作/变更
- `core/gateway_capability_default_enforcement.py`（1）：`F audit_gateway_override` T · 动作/变更
- `core/github_installer.py`（1）：`M GitHubInstaller.install_dry_run` — · 动作/变更
- `core/governance_validation_gate.py`（1）：`F evaluate_governance_validation` T · 计算/构造
- `core/grounded_planner.py`（1）：`F to_task_assign` T · 序列化/转换
- `core/hardware_aware_multimodal_router.py`（3）：`M HardwareAwareMultimodalRouter.route_vision` — · 动作/变更；`M HardwareAwareMultimodalRouter.route_asr` — · 动作/变更；`M HardwareAwareMultimodalRouter.route_with_image` — · 动作/变更
- `core/health_evidence_policy.py`（1）：`F has_health_evidence` T · 判定谓词
- `core/hf_endpoint.py`（1）：`F endpoint_reachable` — · 判定谓词
- `core/huggingface_model_manager.py`（5）：`M HuggingFaceModelManager.download_llm` — · 动作/变更；`M HuggingFaceModelManager.download_vlm` — · 动作/变更；`M HuggingFaceModelManager.download_asr` — · 动作/变更；`M HuggingFaceModelManager.download_embedding` — · 动作/变更；`M HuggingFaceModelManager.download_background` — · 动作/变更
- `core/inflight_task_continuity_contract.py`（1）：`M TaskContinuityStatus.requires_action` T · 判定谓词
- `core/inflight_task_continuity_taxonomy.py`（1）：`F build_task_continuity_verdict_from_report` T · 计算/构造
- `core/interruptibility_registry.py`（1）：`M InterruptibilityRegistry.snapshot_all` T · 只读查询
- `core/lan_discovery.py`（3）：`M _Listener.add_service` — · 动作/变更；`M _Listener.update_service` — · 动作/变更；`M _Listener.remove_service` — · 动作/变更
- `core/local_brain_manager.py`（3）：`M LocalBrainManager.switch_brain` — · 动作/变更；`M LocalBrainManager.remove_model` — · 只读查询；`F check_local_brain` — · 动作/变更
- `core/log_redaction.py`（1）：`F redact_secret` — · 计算/构造
- `core/mainline_convergence.py`（9）：`M MainlineMetadataFrame.is_mainline` T · 判定谓词；`M MainlineExecutionTrace.visits_openclawd` T · 判定谓词；`M MainlineExecutionTrace.visits_capability_dispatch` T · 判定谓词；`M MainlineExecutionTrace.visits_knowledge` T · 判定谓词；`M MainlineConvergenceRegistry.record_from_response` T · 动作/变更；`M MainlineConvergenceRegistry.list_by_path_class` T · 只读查询；`M MainlineConvergenceRegistry.assert_mainline_dominant` T · 动作/变更；`F reset_mainline_convergence_registry` T · 测试复位钩子；`F record_mainline_execution` T · 动作/变更
- `core/mcp_addon_contract.py`（2）：`F is_valid_mcp_addon_contract` T · 判定谓词；`F build_mcp_addon_contract_summary` T · 只读查询
- `core/mcp_gateway.py`（3）：`M MCPDynamicGateway.hot_reload_tool` — · 动作/变更；`M MCPDynamicGateway.sync_tool_registry` — · 动作/变更；`M MCPDynamicGateway.list_github_tools` — · 只读查询
- `core/mcp_loader.py`（4）：`M MCPLoader.read_resource` — · 只读查询；`M MCPLoader.list_resources` — · 只读查询；`M MCPLoader.load_from_config` T · 动作/变更；`M MCPLoader.notify_tools_list_changed` — · 动作/变更
- `core/mesh_coordinator.py`（1）：`F inject_mesh_senders` — · 动作/变更
- `core/mesh_nats_fusion.py`（3）：`M MeshNATSConvergence.submit_participant_result` — · 动作/变更；`M MeshNATSConvergence.subscribe_session` — · 动作/变更；`M MeshNATSConvergence.unsubscribe_session` — · 动作/变更
- `core/message_interop.py`（1）：`F normalize_to_result_envelope` T · 计算/构造
- `core/microsoft_ufo_integration.py`（1）：`F create_ufo_api` — · 计算/构造
- `core/modality_bridge.py`（1）：`F resolve_audio_in` T · 计算/构造
- `core/model_catalog.py`（2）：`F register_ephemeral_spec` T · 动作/变更；`F clear_ephemeral_specs` T · 测试复位钩子
- `core/model_openness.py`（1）：`F audit_registry` T · 动作/变更
- `core/multi_device_canonical_governance.py`（1）：`M MultiDeviceGovernanceVerdict.is_single_device` T · 判定谓词
- `core/multi_device_control_integrity.py`（2）：`M MultiDeviceIntegritySnapshot.gaps_by_area` T · 只读查询；`F build_entry_unification_record` T · 计算/构造
- `core/multi_device_coordination_authority.py`（1）：`F coordination_role_description` — · 只读查询
- `core/multi_device_runtime_harness.py`（1）：`M MultiDeviceCoherenceHarness.to_canonical_projection` — · 序列化/转换
- `core/multi_llm_router.py`（2）：`M MultiLLMRouter.route_local_brain_first` — · 动作/变更；`M MultiLLMRouter.chat_cascade` T · 计算/构造
- `core/multi_subject_closure_machine.py`（3）：`M ClosureTerminalKind.is_success_family` T · 判定谓词；`M ClosureTerminalKind.is_partial_family` T · 判定谓词；`M ClosureTerminalKind.is_failure_family` T · 判定谓词
- `core/native_modal.py`（1）：`F is_native_active` T · 判定谓词
- `core/nats_bus.py`（4）：`M NATSBus.publish_legacy_task_result` T · 动作/变更；`M NATSBus.publish_task_event` T · 动作/变更；`M NATSBus.publish_device_event` T · 动作/变更；`M NATSBus.publish_capability_event` T · 动作/变更
- `core/network_graph_runtime.py`（1）：`F reset_network_graph_runtime` T · 测试复位钩子
- `core/network_topology_runtime.py`（5）：`M NetworkTopologyRuntime.update_edge_state` T · 动作/变更；`F assimilate_nats_state` T · 动作/变更；`F assimilate_gateway_state` T · 动作/变更；`F assimilate_device_connectivity` T · 动作/变更；`F reset_network_topology_runtime` T · 测试复位钩子
- `core/offline_replay_ordering_contract.py`（1）：`F evaluate_replay_sequence` T · 计算/构造
- `core/openclawd.py`（1）：`M OpenClawd.handle_device_command` — · 动作/变更
- `core/openclawd_memory_backflow.py`（1）：`F store_result_envelope` T · 动作/变更
- `core/operational_registration_path.py`（1）：`F assert_operational_registration_path_invariants` T · 动作/变更
- `core/operational_slo_metrics.py`（13）：`M OperationalSLOMetrics.record_dispatch_attempt` T · 动作/变更；`M OperationalSLOMetrics.record_dispatch_success` T · 动作/变更；`M OperationalSLOMetrics.record_dispatch_failure` T · 动作/变更；`M OperationalSLOMetrics.record_route_rejection` T · 动作/变更；`M OperationalSLOMetrics.record_fallback_triggered` T · 动作/变更；`M OperationalSLOMetrics.record_recovery_attempt` T · 动作/变更；`M OperationalSLOMetrics.record_recovery_resumed` T · 动作/变更；`M OperationalSLOMetrics.record_recovery_replayed` T · 动作/变更；`M OperationalSLOMetrics.record_recovery_reissued` T · 动作/变更；`M OperationalSLOMetrics.record_recovery_failed` T · 动作/变更；`M OperationalSLOMetrics.record_startup_recovery_scan` T · 动作/变更；`M OperationalSLOMetrics.record_audit_persist_success` T · 动作/变更；`M OperationalSLOMetrics.record_audit_persist_failure` T · 动作/变更
- `core/outward_runtime_truth.py`（3）：`M OutwardRuntimeTruthRuntime.snapshot_list` T · 只读查询；`M OutwardRuntimeTruthRuntime.compile_count` T · 只读查询；`F classify_signal` T · 计算/构造
- `core/outward_truth_source_registry.py`（2）：`F assert_source_for_field` T · 动作/变更；`F enforce_surface_contract` — · 动作/变更
- `core/peer_trust.py`（2）：`F trust_rank` — · 计算/构造；`M PeerTrustBook.set_trust` — · 动作/变更
- `core/peripheral_capability_boundary.py`（1）：`F classify_peripheral_capability_surface` T · 计算/构造
- `core/phase_contract.py`（1）：`F tri_state_of` T · 只读查询
- `core/pr3_session_continuity_authority.py`（2）：`F govern_takeover_decision` T · 计算/构造；`F classify_local_ai_proposal` T · 计算/构造
- `core/pr4_operator_action_governance.py`（1）：`F clear_operator_action_audit_log` T · 测试复位钩子
- `core/production_baseline.py`（5）：`M ProductionBaselineRegistry.openclawd_owned_artifacts` T · 只读查询；`M ProductionBaselineRegistry.shell_owned_artifacts` T · 只读查询；`M ProductionBaselineRegistry.is_canonical_primary` T · 判定谓词；`M ProductionBaselineRegistry.is_derived_only` T · 判定谓词；`M ProductionBaselineRegistry.is_legacy_secondary` T · 判定谓词
- `core/protocol_drift_registry.py`（4）：`F drift_entries` T · 只读查询；`F drift_summary` T · 只读查询；`F has_unrecognized_drift` T · 判定谓词；`F reset_protocol_drift_registry` T · 测试复位钩子
- `core/proxy_relay.py`（2）：`M ProxyRelay.relay_agent_manifest` — · 动作/变更；`M ProxyRelay.relay_envelope` — · 动作/变更
- `core/react_progress.py`（1）：`M ToolOutcome.retriable` T · 判定谓词
- `core/recovery_truth_surface.py`（2）：`M RecoveryLevel.all_levels` T · 只读查询；`M RecoveryTruthReport.has_deferred` T · 判定谓词
- `core/release_governance_taxonomy.py`（5）：`M OperationalStatus.blocks_release` T · 判定谓词；`M TerminologyRegistry.blocking_terms` T · 只读查询；`M TerminologyRegistry.advisory_only_terms` T · 只读查询；`F classify_issue` T · 计算/构造；`F is_blocking_classification` T · 判定谓词
- `core/remote_execution_mode_resolver.py`（1）：`M ModeResolutionResult.as_remote_execution_mode` T · 序列化/转换
- `core/replay_audit_persistence.py`（1）：`F load_audit_records` T · 动作/变更
- `core/replay_foundation.py`（1）：`M ReplayFoundation.replay_task_timeline` T · 动作/变更
- `core/repo_layout_registry.py`（4）：`M RepoLayoutRegistry.legacy_entries` — · 只读查询；`M RepoLayoutRegistry.entries_by_zone` — · 只读查询；`F is_active_desktop_status_directory` T · 判定谓词；`F build_repo_layout_summary` T · 只读查询
- `core/request_admission.py`（1）：`F admission_snapshot` T · 只读查询
- `core/routing_observability.py`（4）：`M ControlLoopMetrics.record_projection_mismatch` T · 动作/变更；`F reset_routing_metrics` T · 测试复位钩子；`F build_fallback_decision_event` T · 计算/构造；`F build_routing_analytics_snapshot` T · 只读查询
- `core/safe_executor.py`（1）：`M SafeExecutor.as_tool_definition` — · 序列化/转换
- `core/scheduling_truth_harness.py`（2）：`F query_routable_executors_for_task` T · 只读查询；`F assert_scheduling_truth_convergence` T · 动作/变更
- `core/security_policy_loader.py`（4）：`M SecurityPolicy.is_category_allowed` — · 判定谓词；`M SecurityPolicy.is_scene_allowed` — · 判定谓词；`F reload_security_policy` — · 动作/变更；`F check_policy_file_changed` — · 动作/变更
- `core/skill_contract.py`（1）：`F validate_skill_response` T · 动作/变更
- `core/skill_loader.py`（1）：`M SkillLoader.load_package` — · 动作/变更
- `core/skill_package_contract.py`（1）：`F is_valid_skill_package_contract` T · 判定谓词
- `core/skill_registry.py`（1）：`M SkillRegistry.unregister_skill` T · 动作/变更
- `core/slo_metrics.py`（1）：`M SLOMetrics.startup_duration_ms` T · 只读查询
- `core/speech_output.py`（1）：`F native_speech_backend_registered` T · 判定谓词
- `core/state_event_bus.py`（1）：`M StateEventBus.subscriber_count` T · 只读查询
- `core/streaming_speech.py`（1）：`M IncrementalSpeaker.spoke_anything` T · 判定谓词
- `core/subject_facing_foreground.py`（1）：`M SubjectFacingForeground.is_completed` — · 判定谓词
- `core/swarm_coordinator.py`（2）：`M SwarmCoordinator.build_execution_plan_for_orchestration` — · 计算/构造；`M SwarmCoordinator.device_candidates_from_canonical` T · 计算/构造
- `core/system_mode.py`（1）：`M FabricConfig.is_desktop_local` T · 判定谓词
- `core/system_orchestrator.py`（1）：`M SystemOrchestrator.register_hook` T · 动作/变更
- `core/system_resource.py`（5）：`F seed_github_resource` T · 动作/变更；`F seed_academic_resource` T · 动作/变更；`F seed_engineering_resource` T · 动作/变更；`F seed_device_resource` T · 动作/变更；`F seed_local_tool_resource` T · 动作/变更
- `core/tailscale_manager.py`（2）：`M TailscaleManager.is_tailscale_installed` — · 判定谓词；`M TailscaleManager.is_headscale_mode` — · 判定谓词
- `core/takeover_tracking.py`（3）：`M TakeoverTrackingRecord.was_rejected` T · 判定谓词；`F list_takeover_records_for_session` T · 只读查询；`F takeover_tracking_snapshot` T · 只读查询
- `core/target_device_validator.py`（2）：`M CanonicalValidationInput.from_legacy` T · 序列化/转换；`F validate_target_device_from_canonical` T · 动作/变更
- `core/tool_guardian.py`（1）：`F guarded_mcp_call` — · 动作/变更
- `core/tool_permissions.py`（2）：`M ToolPermissionChecker.add_policy` — · 动作/变更；`M ToolPermissionChecker.reset_counters` — · 测试复位钩子
- `core/ui_surface_authority.py`（2）：`F is_legacy_surface` T · 判定谓词；`F is_projection_driven_surface` T · 判定谓词
- `core/unified_action_lifecycle_surface.py`（7）：`M UnifiedActionLifecycleSurface.is_android_result_first_class` T · 判定谓词；`M UnifiedActionLifecycleSurface.has_blocker` T · 判定谓词；`F build_from_dispatch` T · 计算/构造；`F build_from_normalizer_outcome` T · 计算/构造；`F apply_blocker` T · 动作/变更；`F apply_confirmation` T · 动作/变更；`F close_surface` T · 动作/变更
- `core/unified_config.py`（1）：`M UnifiedConfig.on_change` — · 事件回调
- `core/unified_dispatch_readiness_gate.py`（1）：`F reset_dispatch_readiness_gate` T · 测试复位钩子
- `core/unified_execution_governance.py`（1）：`F resolve_execution_conflict` T · 计算/构造
- `core/unified_result_ingress.py`（1）：`M UnifiedResultIngress.reset_replay_session_state` T · 测试复位钩子
- `core/user_preference_memory.py`（1）：`M UserPreferenceMemory.suggest_device_for_task` — · 计算/构造
- `core/vector_backend.py`（1）：`M _QdrantBackend.add_document_vector` — · 动作/变更
- `core/vision_pipeline.py`（2）：`M VisionResult.find_elements_by_type` — · 只读查询；`M VisionResult.find_element_at` — · 只读查询
- `core/voice_duplex_session.py`（1）：`M DuplexSession.next_event` T · 只读查询
- `core/voice_echo_guard.py`（1）：`F is_self_echo` — · 判定谓词
- `core/voice_loop.py`（1）：`M VoiceLoop.process_once` — · 动作/变更

</details>

<details><summary><code>galaxy_gateway/</code> — 53 条</summary>

- `galaxy_gateway/agent_bridge.py`（2）：`M AgentBridge.handoff_from_envelope` T · 计算/构造；`M AgentBridge.build_envelope_v2` T · 计算/构造
- `galaxy_gateway/android/handlers/generic.py`（2）：`F is_generic_forward_blocked_message_type` T · 判定谓词；`F is_generic_forward_compat_message_type` T · 判定谓词
- `galaxy_gateway/android/handlers/registration.py`（2）：`F clear_registration_gaps` T · 测试复位钩子；`F handle_device_reconnect` — · 动作/变更
- `galaxy_gateway/android/handlers/wearos_sync.py`（1）：`F handle_wearos_state_sync` — · 动作/变更
- `galaxy_gateway/android_bridge.py`（7）：`M AndroidBridge.route_liquid_message` — · 动作/变更；`M AndroidBridge.route_phase_change` — · 动作/变更；`M AndroidBridge.cache_transport_handle` T · 只读查询；`M AndroidBridge.push_decision_to_wearos` — · 动作/变更；`M AndroidBridge.query_elements` T · 只读查询；`M AndroidBridge.send_takeover_request` T · 动作/变更；`M AndroidBridge.reconnect_device` T · 动作/变更
- `galaxy_gateway/android_granular_adapter.py`（1）：`M AndroidGranularAdapter.dispatch_aip_message` T · 动作/变更
- `galaxy_gateway/cross_device_switch.py`（1）：`F guard_cross_device` T · 计算/构造
- `galaxy_gateway/daemon_notifier.py`（3）：`M DaemonNotifier.notify_crash_restart` — · 动作/变更；`M DaemonNotifier.notify_too_many_restarts` — · 动作/变更；`M DaemonNotifier.notify_system_pressure` — · 动作/变更
- `galaxy_gateway/device_router.py`（1）：`M DeviceRouter.aggregate_results` T · 计算/构造
- `galaxy_gateway/enhanced_nlu_v2.py`（1）：`M DeviceRegistry.find_device_by_name` — · 只读查询
- `galaxy_gateway/gateway_nats_adapter.py`（1）：`M GatewayNATSAdapter.resolve_task` T · 计算/构造
- `galaxy_gateway/handlers/device_manager.py`（1）：`M DeviceManager.find_best_device_for_task` — · 只读查询
- `galaxy_gateway/multimodal_transfer.py`（5）：`M MultimodalTransferManager.receive_image` — · 动作/变更；`M MultimodalTransferManager.send_video` — · 动作/变更；`M MultimodalTransferManager.send_file_chunk` — · 动作/变更；`M MultimodalTransferManager.receive_file_chunk` — · 动作/变更；`M MultimodalTransferManager.send_screenshot` — · 动作/变更
- `galaxy_gateway/observability.py`（1）：`M TraceContext.child_span` T · 动作/变更
- `galaxy_gateway/orchestrator/parallel_tracker.py`（2）：`M ParallelGroupTracker.finalize_if_complete` T · 计算/构造；`M ParallelGroupTracker.expire_timeouts` T · 动作/变更
- `galaxy_gateway/orchestrator/task_orchestrator.py`（2）：`M TaskOrchestrator.reset_device_counts` — · 测试复位钩子；`M MultiDeviceOrchestrator.submit_multi_device_task` T · 动作/变更
- `galaxy_gateway/protocol/compat.py`（1）：`F extract_parallel_result_payload` — · 计算/构造
- `galaxy_gateway/resumable_transfer.py`（2）：`M ResumableTransferManager.receive_file` — · 动作/变更；`M ResumableTransferManager.write_chunk` — · 动作/变更
- `galaxy_gateway/routing/router.py`（2）：`M RoutingOrchestrator.filter_eligible` T · 计算/构造；`M RoutingOrchestrator.build_message` T · 计算/构造
- `galaxy_gateway/session_roaming.py`（4）：`M SessionRoamingManager.update_task_state` — · 动作/变更；`M SessionRoamingManager.close_session` — · 动作/变更；`M SessionRoamingManager.auto_migrate_on_attention_shift` T · 动作/变更；`M SessionRoamingManager.load_snapshot` — · 只读查询
- `galaxy_gateway/ssot.py`（1）：`F udm_write_upsert` T · 动作/变更
- `galaxy_gateway/task_decomposer.py`（2）：`M TaskDecomposer.decompose_search_and_open` — · 计算/构造；`M TaskDecomposer.decompose_conditional_task` — · 计算/构造
- `galaxy_gateway/transport/websocket_server.py`（1）：`M WebSocketManager.handle_connection` T · 动作/变更
- `galaxy_gateway/wake_event_bus.py`（1）：`M WakeEventBus.clear_dedup_buffer` — · 测试复位钩子
- `galaxy_gateway/wake_router.py`（3）：`M WakeRouter.set_decision_callback` — · 动作/变更；`M WakeRouter.clear_dedup_cache` — · 测试复位钩子；`M WakeRouter.inject_device_info` T · 动作/变更
- `galaxy_gateway/webrtc_proxy.py`（2）：`F order_ice_candidates` T · 计算/构造；`F clear_webrtc_task_session` — · 测试复位钩子
- `galaxy_gateway/websocket_handler.py`（1）：`F handle_response` T · 动作/变更

</details>

<details><summary><code>core/capability_*</code> — 25 条</summary>

- `core/capability_assimilation.py`（3）：`M CapabilityAssimilationLayer.mark_stale_if_expired` T · 动作/变更；`F reset_capability_assimilation_layer` T · 测试复位钩子；`F assimilate_node` T · 动作/变更
- `core/capability_aware_routing_default.py`（1）：`F apply_capability_aware_default` T · 动作/变更
- `core/capability_bus.py`（5）：`M CapabilityBusRole.from_tool_name` T · 序列化/转换；`M CapabilityBus.seed_from_node_registry` T · 动作/变更；`M CapabilityBus.register_mcp_tool` T · 动作/变更；`M CapabilityBus.register_engineering_capability` T · 动作/变更；`M CapabilityBus.register_resource_capability` T · 动作/变更
- `core/capability_graph_selection.py`（1）：`F explain_selection` T · 计算/构造
- `core/capability_manager.py`（1）：`M CapabilityManager.find_capability_by_keyword` — · 只读查询
- `core/capability_network_bridge.py`（2）：`F explain_joint_selection` T · 计算/构造；`F fallback_joint_select` T · 计算/构造
- `core/capability_network_runtime_policy.py`（6）：`F absorb_device_presence_event` T · 动作/变更；`F absorb_heartbeat_event` T · 动作/变更；`F absorb_capability_change_event` T · 动作/变更；`F absorb_path_change_event` T · 动作/变更；`F query_capable_device_executors` T · 只读查询；`F snapshot_canonical_runtime` T · 只读查询
- `core/capability_orchestrator.py`（4）：`M CapabilityOrchestrator.reinitialize` — · 动作/变更；`M CapabilityOrchestrator.list_capabilities` T · 只读查询；`M CapabilityOrchestrator.enable_capability` — · 动作/变更；`M CapabilityOrchestrator.disable_capability` — · 动作/变更
- `core/capability_tier.py`（2）：`F require_main_chain_capability` T · 计算/构造；`F list_capabilities_by_tier` T · 只读查询

</details>

<details><summary><code>core/device_*</code> — 25 条</summary>

- `core/device_activation_registry.py`（1）：`M DeviceActivationRegistry.export_json` — · 动作/变更
- `core/device_agent_manager.py`（3）：`M DeviceAgentManager.register_agent_type` — · 动作/变更；`M DeviceAgentManager.connect_all` — · 动作/变更；`F create_device_api` — · 计算/构造
- `core/device_communication.py`（3）：`M DeviceMessage.to_aip_v3_dict` — · 序列化/转换；`M DeviceCommunication.list_connected_devices` T · 只读查询；`M DeviceCommunication.on_device_message` — · 事件回调
- `core/device_execution_profile.py`（3）：`F build_thin_profile` T · 计算/构造；`F build_rich_profile` T · 计算/构造；`F build_unknown_profile` T · 计算/构造
- `core/device_node_domain_governance.py`（1）：`F classify_registry_surface` T · 计算/构造
- `core/device_node_resolver.py`（2）：`M DeviceNodeResolver.list_supported_device_types` T · 只读查询；`M DeviceNodeResolver.list_supported_transports` T · 只读查询
- `core/device_orchestrator.py`（3）：`M DeviceOrchestrator.parallel_commands` T · 动作/变更；`M DeviceOrchestrator.sync_clipboard` T · 动作/变更；`M DeviceOrchestrator.register_device_in_pool` — · 动作/变更
- `core/device_registry.py`（7）：`M DeviceRegistry.check_offline_devices` T · 动作/变更；`M DeviceRegistry.negotiate_capability` T · 动作/变更；`M DeviceRegistry.add_to_group` — · 动作/变更；`M DeviceRegistry.remove_from_group` — · 动作/变更；`M DeviceRegistry.add_tag` — · 动作/变更；`M DeviceRegistry.remove_tag` — · 动作/变更；`M DeviceRegistry.project_to_contract` T · 序列化/转换
- `core/device_types.py`（1）：`F device_type_to_platform` T · 序列化/转换
- `core/device_worker_convergence.py`（1）：`M DeviceWorkerConvergence.is_worker_registered` — · 判定谓词

</details>

<details><summary><code>core/node_*</code> — 23 条</summary>

- `core/node_capability_loader.py`（1）：`M NodeCapabilityLoader.list_node_actions` — · 只读查询
- `core/node_cognition_activation.py`（2）：`F evaluate_activation_eligibility` T · 计算/构造；`F transition_activation_state` T · 动作/变更
- `core/node_communication.py`（2）：`M NodeRegistry.detect_partitions` — · 动作/变更；`M UniversalCommunicator.activate_self` — · 动作/变更
- `core/node_discovery.py`（7）：`M NodeDiscoveryService.on_node_joined` — · 事件回调；`M NodeDiscoveryService.on_node_left` T · 事件回调；`M NodeDiscoveryService.on_node_updated` — · 事件回调；`M NodeDiscoveryService.deregister_node` — · 动作/变更；`M NodeDiscoveryService.seed_from_registry` T · 动作/变更；`M _DiscoveryProtocol.error_received` — · 事件回调；`F safe_scan_nodes_dir` — · 动作/变更
- `core/node_governance_runtime.py`（1）：`F reset_governance_runtime_cache` T · 测试复位钩子
- `core/node_lifecycle_governor.py`（1）：`F node_governance_snapshot` T · 只读查询
- `core/node_protocol.py`（5）：`M MessageRouter.send_request` — · 动作/变更；`M ProtocolAdapter.to_android_format` — · 序列化/转换；`M ProtocolAdapter.from_android_format` — · 序列化/转换；`M ProtocolAdapter.to_websocket_format` — · 序列化/转换；`M ProtocolAdapter.from_websocket_format` — · 序列化/转换
- `core/node_registry.py`（4）：`M NodeRegistry.register_node_class` — · 动作/变更；`M NodeRegistry.start_health_monitor` T · 动作/变更；`M NodeRegistry.stop_health_monitor` — · 动作/变更；`M NodeRegistry.load_all_nodes` — · 动作/变更

</details>

<details><summary><code>core/android_*</code> — 20 条</summary>

- `core/android_acceptance_evidence_store.py`（1）：`F clear_device_acceptance_evidence` T · 测试复位钩子
- `core/android_delegated_runtime_audit.py`（1）：`F record_delegated_execution_signal` T · 动作/变更
- `core/android_delegated_runtime_lifecycle_coordinator.py`（1）：`M AndroidDelegatedRuntimeLifecycleCoordinator.on_participant_truth_update` T · 事件回调
- `core/android_device_state_store.py`（1）：`F reset_android_device_state_store` T · 测试复位钩子
- `core/android_evaluator_artifact_ingress.py`（1）：`M AndroidEvaluatorArtifactRegistry.list_for_kind` — · 只读查询
- `core/android_mode_gate_policy.py`（1）：`F apply_mode_switch_to_registry` T · 动作/变更
- `core/android_network_participation.py`（1）：`F apply_participation_signal` T · 动作/变更
- `core/android_nl_semantic_chain_contract.py`（5）：`F is_android_nl_carrier` T · 判定谓词；`F build_android_nl_carrier_context` T · 计算/构造；`F assert_v2_is_semantic_authority` T · 动作/变更；`F assert_android_nl_carrier` T · 动作/变更；`F assert_nl_path_type` T · 动作/变更
- `core/android_originated_authority_boundary.py`（2）：`F is_android_main_chain_eligible` T · 判定谓词；`F assert_android_cannot_override_center` T · 动作/变更
- `core/android_participant_evidence_ingress.py`（2）：`M AndroidParticipantStatus.is_negative` T · 判定谓词；`F build_android_participant_evidence_summary` T · 只读查询
- `core/android_participant_truth_ingress.py`（2）：`M AndroidParticipantTruthKind.affects_canonical_state` T · 判定谓词；`M AndroidParticipantTruthKind.is_non_closure_signal` — · 判定谓词
- `core/android_v2_canonical_default_runtime_path.py`（1）：`F classify_android_v2_path` T · 计算/构造
- `core/android_v2_continuity_contract.py`（1）：`F is_android_v2_continuity_healthy` T · 判定谓词

</details>

<details><summary><code>core/delegated_*</code> — 20 条</summary>

- `core/delegated_flow_decision_history.py`（3）：`M HistoryEvidenceStatus.allows_runtime_closure` T · 判定谓词；`M HistoryEvidenceStatus.is_definitive_gap` T · 判定谓词；`F record_delegated_flow_event` T · 动作/变更
- `core/delegated_flow_entity.py`（1）：`M DelegatedFlowPhase.is_executing_or_later` T · 判定谓词
- `core/delegated_flow_persistence.py`（9）：`M DelegatedFlowPersistenceBundle.persist_all` T · 动作/变更；`F persist_session_snapshot` T · 只读查询；`F restore_sessions` T · 动作/变更；`F persist_contract_snapshot` T · 只读查询；`F restore_contracts` T · 动作/变更；`F persist_binding_snapshot` T · 只读查询；`F restore_bindings` T · 动作/变更；`F persist_flow_entity_snapshot` T · 只读查询；`F restore_flow_entities` T · 动作/变更
- `core/delegated_flow_post_graduation_governance.py`（1）：`M GovernanceVerdict.is_violation` T · 判定谓词
- `core/delegated_flow_recovery_coordinator.py`（6）：`M DelegatedFlowRecoveryCoordinator.list_recent_attempts` T · 只读查询；`F decide_recovery` T · 计算/构造；`F decide_recovery_from_continuity_artifact` T · 计算/构造；`F begin_recovery_attempt` T · 动作/变更；`F complete_recovery_attempt` T · 动作/变更；`F suppress_recovery_attempt` T · 动作/变更

</details>

<details><summary><code>core/cognitive/</code> — 19 条</summary>

- `core/cognitive/cognitive_activation_budget.py`（4）：`M ActivationBudget.is_narrow` T · 判定谓词；`M ActivationBudget.is_moderate` T · 判定谓词；`M ActivationBudget.is_broad` T · 判定谓词；`F apply_candidate_narrowing` T · 动作/变更
- `core/cognitive/cognitive_execution_policy.py`（3）：`M CognitiveExecutionHint.is_manifest` — · 判定谓词；`M CognitiveExecutionHint.is_liminal` — · 判定谓词；`M CognitiveExecutionHint.is_passive` — · 判定谓词
- `core/cognitive/cognitive_field_engine.py`（2）：`M CognitiveFieldEngine.add_tick_listener` T · 动作/变更；`M CognitiveFieldEngine.remove_tick_listener` T · 动作/变更
- `core/cognitive/liminal_dynamics.py`（1）：`M LiminalDynamics.can_transition_to_manifest` T · 判定谓词
- `core/cognitive/long_term_memory.py`（2）：`M LongTermMemory.retrieve_entry` T · 只读查询；`M LongTermMemory.forget_namespace` T · 动作/变更
- `core/cognitive/memory_bias_layer.py`（4）：`M MemoryBias.is_continuity` T · 判定谓词；`M MemoryBias.is_retrieval` T · 判定谓词；`M MemoryBias.is_novelty` T · 判定谓词；`F build_memory_bias_active_scope_diagnostics` T · 计算/构造
- `core/cognitive/pattern_miner.py`（1）：`M PatternMiner.mine_full` — · 动作/变更
- `core/cognitive/state_interpreter.py`（2）：`M StateInterpreter.interpret_snapshot` T · 只读查询；`M StateInterpreter.last_region` T · 只读查询

</details>

<details><summary><code>core/unified/</code> — 19 条</summary>

- `core/unified/capability_resolver.py`（1）：`M CapabilityResolver.resolve_by_tag` T · 计算/构造
- `core/unified/command_envelope.py`（3）：`M CommandEnvelope.make_cancel` T · 计算/构造；`M CommandEnvelope.make_interrupt` T · 计算/构造；`M CommandEnvelope.is_cancel` T · 判定谓词
- `core/unified/device_health.py`（1）：`M DeviceHealthScorer.reset_device` T · 测试复位钩子
- `core/unified/error_mapper.py`（3）：`M ErrorMapper.from_legacy_gateway_error` T · 序列化/转换；`M ErrorMapper.from_legacy_device_error` T · 序列化/转换；`M ErrorMapper.from_legacy_executor_error` T · 序列化/转换
- `core/unified/idempotency.py`（1）：`M IdempotencyStore.record_failed` T · 动作/变更
- `core/unified/llm_router.py`（2）：`F reset_routing_telemetry` T · 测试复位钩子；`M UnifiedLLMRouter.reload_policy` T · 动作/变更
- `core/unified/release_gate.py`（3）：`M ReleaseGate.clear_override` T · 测试复位钩子；`M ReleaseGate.clear_all_overrides` T · 测试复位钩子；`M ReleaseGate.list_flags` T · 只读查询
- `core/unified/state_schema.py`（5）：`M TaskState.add_judge_record` — · 动作/变更；`M TaskState.mark_verified` — · 动作/变更；`M TaskState.resolve_failure` — · 计算/构造；`M TaskState.set_goal` — · 动作/变更；`M TaskState.set_phase` — · 动作/变更

</details>

<details><summary><code>core/mesh/</code> — 18 条</summary>

- `core/mesh/android_mesh_participant_signal_adapter.py`（3）：`F classify_android_proof_quality_for_signals` T · 只读查询；`F evaluate_center_runtime_status_with_android_signals` T · 只读查询；`F apply_android_participation_signals_batch` T · 动作/变更
- `core/mesh/body_mesh_registry.py`（1）：`M BodyEntry.has_role` — · 判定谓词
- `core/mesh/device_role_allocator.py`（2）：`M DeviceRoleAllocator.register_capability_rule` T · 动作/变更；`M DeviceRoleAllocator.allocate_all` T · 动作/变更
- `core/mesh/live_mesh_session_coordinator.py`（1）：`M LiveMeshSessionCoordinator.on_android_participant_signal` T · 事件回调
- `core/mesh/mesh_auto_enrollment.py`（3）：`M MeshAutoEnrollmentService.list_enrolled_device_ids` T · 只读查询；`F notify_readiness_confirmed` T · 动作/变更；`F notify_device_lost` T · 动作/变更
- `core/mesh/mesh_runtime_center_state.py`（2）：`F is_valid_center_transition` T · 判定谓词；`M MeshParticipantEligibilityStatus.can_participate` T · 判定谓词
- `core/mesh/mesh_session_coordinator.py`（3）：`M MeshSessionCoordinator.update_with_dispatch_result` T · 动作/变更；`M MeshSessionCoordinator.update_with_takeover_result` T · 动作/变更；`M MeshSessionCoordinator.update_with_merged_result` T · 动作/变更
- `core/mesh/mesh_session_lifecycle.py`（3）：`M MeshSessionLifecycleCoordinator.list_active_session_ids` T · 只读查询；`M MeshSessionLifecycleCoordinator.list_restorable_session_ids` — · 只读查询；`F associate_resumed_execution_with_session` T · 动作/变更

</details>

<details><summary><code>core/orchestration/</code> — 18 条</summary>

- `core/orchestration/execution.py`（2）：`M ExecutionPipeline.run_local` — · 动作/变更；`M ExecutionPipeline.run_remote` — · 动作/变更
- `core/orchestration/global_arbiter.py`（2）：`M GlobalArbiter.suggest_device` T · 计算/构造；`F reset_global_arbiter` T · 测试复位钩子
- `core/orchestration/helpers.py`（5）：`M OrchestrationHelpers.emit_audit` T · 动作/变更；`M OrchestrationHelpers.emit_routing_decision_event` — · 动作/变更；`M OrchestrationHelpers.apply_latency_budget` — · 动作/变更；`M OrchestrationHelpers.build_permission_safety_state` — · 计算/构造；`M OrchestrationHelpers.apply_operator_overrides` — · 动作/变更
- `core/orchestration/lifecycle.py`（2）：`M LifecycleManager.is_cancelled` T · 判定谓词；`M LifecycleManager.finalise_plan` T · 计算/构造
- `core/orchestration/planning.py`（2）：`M PlanningPipeline.determine_execution_path` T · 计算/构造；`M PlanningPipeline.build_intent_profile` — · 计算/构造
- `core/orchestration/reflection.py`（3）：`M ReflectionPipeline.build_mainline_convergence_stamp` — · 计算/构造；`M ReflectionPipeline.build_execution_trace` — · 计算/构造；`M ReflectionPipeline.build_decision_timeline_snapshot` — · 只读查询
- `core/orchestration/state.py`（2）：`M SessionMemoryManager.record_turn` T · 动作/变更；`M ContinuumStateAdapter.run_continuum` — · 动作/变更

</details>

<details><summary><code>core/ugcp_*</code> — 15 条</summary>

- `core/ugcp_control_transfer_profile.py`（6）：`F map_from_dispatch_preparation_state` T · 计算/构造；`F map_from_handoff_contract_status` T · 计算/构造；`F map_from_takeover_status` T · 计算/构造；`F map_from_delegated_signal` T · 计算/构造；`F infer_terminal_reason` T · 计算/构造；`F build_transfer_merge_reason` T · 计算/构造
- `core/ugcp_coordination_profile.py`（8）：`F map_from_mesh_session_status` T · 计算/构造；`F map_from_coordinator_status` T · 计算/构造；`F map_from_participant_role` T · 计算/构造；`F map_from_authority_scope` T · 计算/构造；`F map_from_barrier_status` T · 计算/构造；`F map_from_aggregation_mode` T · 计算/构造；`F infer_terminal_outcome` T · 计算/构造；`F build_coordination_merge_reason` T · 计算/构造
- `core/ugcp_truth_event_model.py`（1）：`F is_authoritative_transition_event` T · 判定谓词

</details>

<details><summary><code>nodes/Node_71_MultiDeviceCoordination/</code> — 15 条</summary>

- `nodes/Node_71_MultiDeviceCoordination/core/canonical_device_view_adapter.py`（2）：`M CoordinationDeviceView.mark_task_assigned` — · 动作/变更；`M CoordinationDeviceView.mark_task_released` — · 动作/变更
- `nodes/Node_71_MultiDeviceCoordination/core/device_discovery.py`（2）：`M DeviceDiscovery.add_device` — · 动作/变更；`M DeviceDiscovery.discover_now` — · 动作/变更
- `nodes/Node_71_MultiDeviceCoordination/core/fault_tolerance.py`（4）：`M FailoverManager.set_primary` — · 动作/变更；`M FailoverManager.add_secondary` — · 动作/变更；`M FailoverManager.remove_secondary` — · 动作/变更；`M FailoverManager.register_health_checker` — · 动作/变更
- `nodes/Node_71_MultiDeviceCoordination/core/state_synchronizer.py`（1）：`M StateSynchronizer.handle_gossip_message` — · 动作/变更
- `nodes/Node_71_MultiDeviceCoordination/main.py`（2）：`M Device.to_unified_model` — · 序列化/转换；`M Device.from_unified_model` — · 序列化/转换
- `nodes/Node_71_MultiDeviceCoordination/models/device.py`（1）：`M DeviceRegistry.count_by_state` — · 只读查询
- `nodes/Node_71_MultiDeviceCoordination/models/task.py`（3）：`M Task.update_progress` — · 动作/变更；`M TaskQueue.dequeue` — · 动作/变更；`M TaskQueue.is_empty` — · 判定谓词

</details>

<details><summary><code>core/task_*</code> — 11 条</summary>

- `core/task_cost_ledger.py`（1）：`F current_task_bill` T · 只读查询
- `core/task_envelope_lifecycle_registry.py`（3）：`M TaskEnvelopeLifecycleRegistry.cancel_timed_out` — · 动作/变更；`M TaskEnvelopeLifecycleRegistry.resume_for_device` — · 动作/变更；`M TaskEnvelopeLifecycleRegistry.all_pending_task_ids` — · 只读查询
- `core/task_graph_runtime.py`（3）：`M TaskGraphRuntime.register_fanin` T · 动作/变更；`F result_envelope_to_node_update` T · 序列化/转换；`F project_workflow_to_graph` T · 计算/构造
- `core/task_lifecycle.py`（2）：`M TaskLifecycleManager.mark_interrupted` T · 动作/变更；`M TaskLifecycleManager.run_with_lifecycle` T · 动作/变更
- `core/task_memory.py`（1）：`M TaskMemory.evict_expired` T · 动作/变更
- `core/task_result_canonical_truth_chain.py`（1）：`M IncompleteResultLedger.all_incomplete` T · 只读查询

</details>

<details><summary><code>core/attached_runtime_*</code> — 10 条</summary>

- `core/attached_runtime_recovery_readiness.py`（1）：`F clear_seq_context_for_reconnect` T · 测试复位钩子
- `core/attached_runtime_reuse_binding.py`（3）：`M ReuseInvalidationReason.is_lifecycle_invalidation` T · 判定谓词；`M AttachedRuntimeReuseBindingRecord.is_invalidated` T · 判定谓词；`M AttachedRuntimeReuseBindingRecord.has_dispatch_binding` T · 判定谓词
- `core/attached_runtime_reuse_dispatch.py`（3）：`M ReuseDispatchResolution.is_reusable` T · 判定谓词；`M ReuseDispatchResolution.has_no_binding` T · 判定谓词；`M ReuseDispatchResolution.is_new_binding` T · 判定谓词
- `core/attached_runtime_session.py`（1）：`M AttachedRuntimeSessionRecord.is_eligible_for_execution` T · 判定谓词
- `core/attached_runtime_session_registry.py`（2）：`F lookup_session_by_attachment_id` T · 只读查询；`F record_mode_switch_in_session` T · 动作/变更

</details>

<details><summary><code>core/hybrid_*</code> — 10 条</summary>

- `core/hybrid_execution_policy.py`（3）：`M HybridExecutionMode.is_concurrent` T · 判定谓词；`M HybridExecutionMode.is_degrade_chain` T · 判定谓词；`M HybridExecutionPolicy.describe_mode` T · 只读查询
- `core/hybrid_orchestration_continuity.py`（7）：`M HybridOrchestrationContinuityRegistry.list_non_terminal` T · 只读查询；`M HybridOrchestrationContinuityRegistry.list_terminal` T · 只读查询；`M HybridOrchestrationContinuityRegistry.list_interrupted` T · 只读查询；`M HybridOrchestrationContinuityRegistry.clear_terminal` T · 测试复位钩子；`F save_hybrid_execution` — · 动作/变更；`F load_hybrid_execution` T · 动作/变更；`F recover_hybrid_executions` T · 动作/变更

</details>

<details><summary><code>core/model_topology/</code> — 10 条</summary>

- `core/model_topology/canonical_model_supply_state.py`（1）：`M NativeMultimodalCapabilityRegistry.register_many` T · 动作/变更
- `core/model_topology/config_bridge.py`（1）：`M ConfigBridge.build_inventory` T · 计算/构造
- `core/model_topology/model_supply_graph.py`（3）：`M ModelSupplyGraph.edges_of_kind` T · 只读查询；`M ModelSupplyGraph.nodes_by_category` T · 只读查询；`M ModelSupplyGraph.nodes_by_provider` — · 只读查询
- `core/model_topology/provider_inventory.py`（4）：`M ProviderInventory.unavailable_entries` T · 只读查询；`M ProviderInventory.top_by_quality` T · 只读查询；`M ProviderInventory.top_by_speed` T · 只读查询；`M ProviderInventory.top_by_composite` — · 只读查询
- `core/model_topology/topology_router.py`（1）：`M TopologyRouter.route_all_phases` T · 动作/变更

</details>

<details><summary><code>core/desktop_*</code> — 9 条</summary>

- `core/desktop_consumption_adapter.py`（1）：`M DesktopClientViewModel.readiness_label` T · 只读查询
- `core/desktop_presence_runtime.py`（5）：`M DesktopPresenceRuntime.snapshot_continuous_perception` T · 只读查询；`M DesktopPresenceRuntime.permission_safety_summary` T · 只读查询；`M DesktopPresenceRuntime.set_operator_override` T · 动作/变更；`M DesktopPresenceRuntime.operator_override_summary` T · 只读查询；`M DesktopPresenceRuntime.decision_timeline_replay` T · 只读查询
- `core/desktop_presence_system.py`（3）：`M DesktopPresenceStateMachine.simulate_elapsed_time_for_testing` T · 测试复位钩子；`F list_presence_mode_names` T · 只读查询；`F iter_presence_transition_targets` T · 只读查询

</details>

<details><summary><code>core/canonical_*</code> — 8 条</summary>

- `core/canonical_ownership_truth_bridge.py`（2）：`F is_recovery_eligible` T · 判定谓词；`F build_ownership_aware_replay_execution_record` T · 计算/构造
- `core/canonical_session_axis.py`（2）：`F resolve_session_family_for_identifier` T · 计算/构造；`F build_session_axis_snapshot` T · 只读查询
- `core/canonical_task_dispatch_chain.py`（4）：`F classify_dispatch_path` T · 计算/构造；`F is_canonical_path` T · 判定谓词；`F is_android_inbound_path` T · 判定谓词；`F build_dispatch_chain_snapshot` T · 只读查询

</details>

<details><summary><code>core/runtime/</code> — 8 条</summary>

- `core/runtime/execution_target_policy_engine.py`（2）：`F apply_failure_handling_policy` T · 动作/变更；`F apply_degraded_readiness_policy` T · 动作/变更
- `core/runtime/runtime_observability_sink.py`（5）：`M RuntimeObservabilitySink.list_device_lifecycle_events` T · 只读查询；`M RuntimeObservabilitySink.list_mesh_session_transition_events` T · 只读查询；`M RuntimeObservabilitySink.list_dispatch_decision_events` T · 只读查询；`M RuntimeObservabilitySink.list_recovery_decision_events` T · 只读查询；`M RuntimeObservabilitySink.counters` T · 只读查询
- `core/runtime/source_dispatch_orchestrator.py`（1）：`F reset_live_mesh_runtime_proof_snapshot` T · 测试复位钩子

</details>

<details><summary><code>core/v2_*</code> — 8 条</summary>

- `core/v2_android_recovery_continuity_hardening.py`（7）：`F classify_session_reuse` T · 计算/构造；`F assess_attached_runtime_truth` T · 计算/构造；`F classify_evidence_ingress` T · 计算/构造；`F assess_recovery_closure_quality` T · 计算/构造；`F classify_result_delivery` T · 计算/构造；`F interpret_replay_sequence` T · 计算/构造；`F build_recovery_participation_report` T · 计算/构造
- `core/v2_android_truth_ssot.py`（1）：`F build_v2_android_truth_block_multi` T · 计算/构造

</details>

<details><summary><code>core/control_plane/</code> — 7 条</summary>

- `core/control_plane/audit_ledger.py`（2）：`M AuditLedger.verify_chain` T · 动作/变更；`M AuditLedger.to_dag` T · 序列化/转换
- `core/control_plane/security_interceptor.py`（1）：`M SecurityInterceptor.check_and_intercept` T · 动作/变更
- `core/control_plane/smart_scheduler.py`（1）：`M DeviceScoringEngine.rank_devices` T · 计算/构造
- `core/control_plane/swarm_manifest.py`（1）：`M SwarmAgentManifest.to_agent_execute_payload` T · 序列化/转换
- `core/control_plane/swarm_scaler.py`（2）：`M SwarmScaler.autoscale` T · 动作/变更；`M SwarmScaler.managed_workers` — · 只读查询

</details>

<details><summary><code>core/cross_*</code> — 7 条</summary>

- `core/cross_device_dispatch_boundary.py`（5）：`F classify_dispatch_call` T · 计算/构造；`F is_canonical_dispatch` T · 判定谓词；`F is_controlled_fallback` T · 判定谓词；`F is_compat_fallback` T · 判定谓词；`F is_legacy_bypass` T · 判定谓词
- `core/cross_device_sync.py`（1）：`F push_task_state_to_device` — · 动作/变更
- `core/cross_repo_protocol_consistency.py`（1）：`F is_canonical_surface` T · 判定谓词

</details>

<details><summary><code>core/execution_observability/</code> — 7 条</summary>

- `core/execution_observability/event_schema.py`（1）：`M ExecutionEvent.projection_summary` T · 只读查询
- `core/execution_observability/executor_level.py`（1）：`M ExecutorLevel.from_win_exec_level` T · 序列化/转换
- `core/execution_observability/normalizers.py`（4）：`F normalize_e2e_context` T · 计算/构造；`F normalize_task_envelope` T · 计算/构造；`F normalize_task_graph_result` T · 计算/构造；`F normalize_arbiter_attempt` T · 计算/构造
- `core/execution_observability/trace_schema.py`（1）：`M TraceCorrelation.from_task_graph` T · 序列化/转换

</details>

<details><summary><code>core/continuation_*</code> — 6 条</summary>

- `core/continuation_rebind_registry.py`（6）：`M ContinuationRebindRegistry.register_new_waiter` T · 动作/变更；`M ContinuationRebindRegistry.is_pending_rebind` T · 判定谓词；`M ContinuationRebindRegistry.is_loop_closed` T · 判定谓词；`M ContinuationRebindRegistry.pending_rebind_count` T · 只读查询；`M ContinuationRebindRegistry.rebound_count` T · 只读查询；`M ContinuationRebindRegistry.list_pending_task_ids` T · 只读查询

</details>

<details><summary><code>core/flow_*</code> — 6 条</summary>

- `core/flow_continuity_coordinator.py`（6）：`F coordinate_attach` T · 动作/变更；`F coordinate_reattach_process_recreation` T · 动作/变更；`F coordinate_stale_identity` T · 动作/变更；`F coordinate_duplicate_signal` T · 动作/变更；`F coordinate_partial_result` T · 动作/变更；`F coordinate_v2_restart_recovery` T · 动作/变更

</details>

<details><summary><code>core/truth_*</code> — 6 条</summary>

- `core/truth_conflict_enforcement.py`（4）：`F assert_canonical_write_precedes_compat_write` T · 动作/变更；`F assert_no_parallel_write_authority` T · 动作/变更；`F check_compat_write_is_mirror_only` T · 动作/变更；`F is_truth_convergence_healthy` T · 判定谓词
- `core/truth_integration_layer.py`（1）：`F is_device_available_canonical` T · 判定谓词
- `core/truth_projection_boundary.py`（1）：`F classify_surface_boundary` T · 计算/构造

</details>

<details><summary><code>launcher/</code> — 6 条</summary>

- `launcher/bootstrap.py`（1）：`M SystemConfig.has_llm_api` T · 判定谓词
- `launcher/dependency_resolver.py`（1）：`M DependencyResolver.resolve_all_startup_order` — · 计算/构造
- `launcher/gateway.py`（1）：`F wait_for_gateway` T · 动作/变更
- `launcher/nodes.py`（1）：`F equivalent_legacy_command` T · 计算/构造
- `launcher/ui.py`（2）：`F render_banner` — · 计算/构造；`F color_enabled` — · 判定谓词

</details>

<details><summary><code>core/governance/</code> — 5 条</summary>

- `core/governance/budget_enforcer.py`（3）：`M BudgetEnforcer.enforce_pre_call` T · 动作/变更；`M BudgetEnforcer.reset_session` T · 测试复位钩子；`M BudgetEnforcer.all_session_ids` — · 只读查询
- `core/governance/tool_governor.py`（2）：`M ToolGovernor.clear_audit_log` — · 测试复位钩子；`M ToolGovernor.reset_bucket` T · 测试复位钩子

</details>

<details><summary><code>core/runtime_*</code> — 5 条</summary>

- `core/runtime_closure_audit.py`（2）：`F run_closure_audit` T · 动作/变更；`F persist_conflict_artifacts` T · 只读查询
- `core/runtime_invariant_enforcement.py`（2）：`F check_invariant` T · 动作/变更；`F check_cross_repo_assumption` T · 动作/变更
- `core/runtime_readiness_matrix.py`（1）：`F is_release_blocked` T · 判定谓词

</details>

<details><summary><code>core/adapters/</code> — 4 条</summary>

- `core/adapters/ble_adapter.py`（1）：`M BLEAdapter.list_connected` — · 只读查询
- `core/adapters/tailscale_p2p_adapter.py`（1）：`M TailscaleP2PAdapter.list_registered_devices` — · 只读查询
- `core/adapters/tcp_adapter.py`（2）：`M TCPAdapter.connect_to_peer` — · 动作/变更；`M TCPAdapter.discover_peers` — · 动作/变更

</details>

<details><summary><code>core/nodes/</code> — 4 条</summary>

- `core/nodes/node_fabric_registry.py`（4）：`M NodeFabricRegistry.mark_offline_if_stale` T · 动作/变更；`M NodeFabricRegistry.list_by_capability` T · 只读查询；`M NodeFabricRegistry.expire_stale_capabilities` T · 动作/变更；`F reset_node_fabric_registry` T · 测试复位钩子

</details>

<details><summary><code>nodes/Node_70_AutonomousLearning/</code> — 4 条</summary>

- `nodes/Node_70_AutonomousLearning/core/autonomous_learning_engine.py`（4）：`M AutonomousLearningEngine.generalize_skill` — · 动作/变更；`M AutonomousLearningEngine.find_similar_skills` — · 只读查询；`M AutonomousLearningEngine.process_observation` — · 动作/变更；`M AutonomousLearningEngine.update_experience_outcome` — · 动作/变更

</details>

<details><summary><code>core/agentic/</code> — 3 条</summary>

- `core/agentic/workflow.py`（3）：`F from_task_agent` — · 序列化/转换；`F from_team` — · 序列化/转换；`F from_fractal` — · 序列化/转换

</details>

<details><summary><code>core/continuum/</code> — 3 条</summary>

- `core/continuum/return_engine.py`（1）：`M ReturnEngine.force_return` T · 动作/变更
- `core/continuum/temporal_engine.py`（2）：`M DwellGuard.remaining_ms` T · 只读查询；`M TemporalEngine.smoothed_signals` T · 只读查询

</details>

<details><summary><code>core/device_formation/</code> — 3 条</summary>

- `core/device_formation/formation_auto_enrollment.py`（2）：`M FormationAutoEnrollmentManager.update_device_readiness` T · 动作/变更；`M FormationAutoEnrollmentManager.list_active_device_ids` T · 只读查询
- `core/device_formation/formation_runtime_coordinator.py`（1）：`M FormationParticipantStatus.is_viable` T · 判定谓词

</details>

<details><summary><code>core/multimodal/</code> — 3 条</summary>

- `core/multimodal/perception_source_registry.py`（3）：`M PerceptionSourceRegistry.update_quality` T · 动作/变更；`M PerceptionSourceRegistry.sources_by_type` T · 只读查询；`M PerceptionSourceRegistry.degraded_sources` T · 只读查询

</details>

<details><summary><code>core/perception/</code> — 3 条</summary>

- `core/perception/desktop_perception_store.py`（2）：`M DesktopPerceptionStore.has_fresh_frame` T · 判定谓词；`M DesktopPerceptionStore.take_fresh_system_audio_for_autoinject` T · 动作/变更
- `core/perception/perception_fact_boundary.py`（1）：`F classify_perception_surface` T · 计算/构造

</details>

<details><summary><code>core/presence/</code> — 3 条</summary>

- `core/presence/presence_director.py`（2）：`M PresenceDirector.on_phase_transition` T · 事件回调；`M PresenceDirector.refresh_presence` T · 动作/变更
- `core/presence/presence_projection.py`（1）：`M PresenceProjection.last_events` T · 只读查询

</details>

<details><summary><code>core/resilience/</code> — 3 条</summary>

- `core/resilience/circuit_breaker.py`（1）：`M CircuitBreaker.trip` T · 动作/变更
- `core/resilience/metrics.py`（2）：`M ResilienceMetrics.record_circuit_open` T · 动作/变更；`M ResilienceMetrics.rejection_rate_per_minute` T · 只读查询

</details>

<details><summary><code>core/session_*</code> — 3 条</summary>

- `core/session_execution_lane.py`（1）：`M SessionExecutionLaneManager.list_lanes` — · 只读查询
- `core/session_manager.py`（2）：`M SessionManager.record_verdict` — · 动作/变更；`M SessionManager.export_jsonl` — · 动作/变更

</details>

<details><summary><code>nodes/Node_112_SelfHealing/</code> — 3 条</summary>

- `nodes/Node_112_SelfHealing/main.py`（3）：`M SelfHealingEngine.unregister_health_check` — · 动作/变更；`M SelfHealingEngine.register_recovery_handler` — · 动作/变更；`M SelfHealingEngine.run_once` T · 动作/变更

</details>

<details><summary><code>nodes/Node_116_ExternalToolWrapper/</code> — 3 条</summary>

- `nodes/Node_116_ExternalToolWrapper/main.py`（3）：`M ExternalToolWrapper.unregister_tool` — · 动作/变更；`M ExternalToolWrapper.register_custom_handler` — · 动作/变更；`M ExternalToolWrapper.execute_custom` — · 动作/变更

</details>

<details><summary><code>nodes/Node_43_MAVLink/</code> — 3 条</summary>

- `nodes/Node_43_MAVLink/universal_drone_controller.py`（3）：`M UniversalDroneController.start_recording` — · 动作/变更；`M UniversalDroneController.stop_recording` — · 动作/变更；`M UniversalDroneController.execute_waypoint_mission` — · 动作/变更

</details>

<details><summary><code>core/agent/</code> — 2 条</summary>

- `core/agent/intent_router.py`（1）：`M IntentResult.is_execution` T · 判定谓词
- `core/agent/policy_loader.py`（1）：`F reload_policies` T · 动作/变更

</details>

<details><summary><code>core/capability_runtime/</code> — 2 条</summary>

- `core/capability_runtime/capability_constraint.py`（1）：`M CapabilityConstraintFlags.has_any_constraint` T · 判定谓词
- `core/capability_runtime/capability_preference.py`（1）：`M CapabilityPreference.has_preference` T · 判定谓词

</details>

<details><summary><code>core/cross_device_policy/</code> — 2 条</summary>

- `core/cross_device_policy/routing_policy.py`（2）：`M RoutingPolicy.source_assignment` T · 只读查询；`M RoutingPolicy.devices_with_role` T · 只读查询

</details>

<details><summary><code>core/tts/</code> — 2 条</summary>

- `core/tts/edge_tts_engine.py`（2）：`M EdgeTTSEngine.set_voice` — · 动作/变更；`M EdgeTTSEngine.set_rate` — · 动作/变更

</details>

<details><summary><code>nodes/Node_05_Auth/</code> — 2 条</summary>

- `nodes/Node_05_Auth/main.py`（2）：`M AuthManager.has_permission` — · 判定谓词；`M AuthManager.delete_user` — · 动作/变更

</details>

<details><summary><code>nodes/Node_109_ProactiveSensing/</code> — 2 条</summary>

- `nodes/Node_109_ProactiveSensing/main.py`（2）：`M ProactiveSensingEngine.unregister_sensor` — · 动作/变更；`M ProactiveSensingEngine.remove_rule` — · 动作/变更

</details>

<details><summary><code>nodes/Node_54_SymbolicMath/</code> — 2 条</summary>

- `nodes/Node_54_SymbolicMath/main.py`（2）：`M CrossDisciplinaryVerifier.verify_physics` — · 动作/变更；`M CrossDisciplinaryVerifier.verify_engineering` — · 动作/变更

</details>

<details><summary><code>nodes/Node_72_KnowledgeBase/</code> — 2 条</summary>

- `nodes/Node_72_KnowledgeBase/knowledge_base_system.py`（2）：`M KnowledgeBaseSystem.export_knowledge` — · 动作/变更；`M KnowledgeBaseSystem.import_knowledge` — · 动作/变更

</details>

<details><summary><code>core/audit_layer/</code> — 1 条</summary>

- `core/audit_layer/fresh_dual_repo_code_audit.py`（1）：`F assert_fresh_audit_invariants` T · 动作/变更

</details>

<details><summary><code>core/capabilities/</code> — 1 条</summary>

- `core/capabilities/canonical_dispatcher.py`（1）：`M CanonicalDispatcher.bus_catalog` T · 只读查询

</details>

<details><summary><code>core/execution/</code> — 1 条</summary>

- `core/execution/decision_executor.py`（1）：`M PolicyGate.check_action_level` T · 动作/变更

</details>

<details><summary><code>core/execution_*</code> — 1 条</summary>

- `core/execution_spine.py`（1）：`F route_via_spine` T · 动作/变更

</details>

<details><summary><code>core/generative_ui/</code> — 1 条</summary>

- `core/generative_ui/runtime.py`（1）：`M GenerativeUIRuntime.render_surface_dict` T · 计算/构造

</details>

<details><summary><code>core/interaction/</code> — 1 条</summary>

- `core/interaction/pending_decision_registry.py`（1）：`M PendingDecisionRegistry.sweep_expired` — · 动作/变更

</details>

<details><summary><code>core/operator_*</code> — 1 条</summary>

- `core/operator_execution_observability_surface.py`（1）：`M OperatorExecutionEvidenceEntry.requires_operator_attention` T · 判定谓词

</details>

<details><summary><code>core/orchestration*</code> — 1 条</summary>

- `core/orchestration_review_surface.py`（1）：`F increment_legacy_dispatch_counter` T · 动作/变更

</details>

<details><summary><code>core/output/</code> — 1 条</summary>

- `core/output/voice_channel.py`（1）：`M VoiceChannel.build_with_synthesis` — · 计算/构造

</details>

<details><summary><code>core/persona/</code> — 1 条</summary>

- `core/persona/state_store.py`（1）：`M StateStore.reset_state` T · 测试复位钩子

</details>

<details><summary><code>core/queueing/</code> — 1 条</summary>

- `core/queueing/async_queue.py`（1）：`M AsyncTaskQueue.force_stop` — · 动作/变更

</details>

<details><summary><code>core/reliability_contract/</code> — 1 条</summary>

- `core/reliability_contract/retry_policy.py`（1）：`M RetryPolicy.has_retries` T · 判定谓词

</details>

<details><summary><code>core/routing_explanation/</code> — 1 条</summary>

- `core/routing_explanation/live_decision.py`（1）：`M LiveRoutingDecisionBuilder.record_policy_band` — · 动作/变更

</details>

<details><summary><code>nodes/Node_04_Router/</code> — 1 条</summary>

- `nodes/Node_04_Router/qwen_think_logic.py`（1）：`M QwenThinkRouter.plan_route` — · 计算/构造

</details>

<details><summary><code>nodes/Node_106_GitHubFlow/</code> — 1 条</summary>

- `nodes/Node_106_GitHubFlow/main.py`（1）：`M GitHubClient.create_pull_request` — · 计算/构造

</details>

<details><summary><code>nodes/Node_108_MetaCognition/</code> — 1 条</summary>

- `nodes/Node_108_MetaCognition/main.py`（1）：`M MetaCognitionEngine.comprehend` — · 计算/构造

</details>

<details><summary><code>nodes/Node_110_SmartOrchestrator/</code> — 1 条</summary>

- `nodes/Node_110_SmartOrchestrator/main_enhanced.py`（1）：`M QwenEnhancedOrchestrator.think_and_plan` — · 计算/构造

</details>

<details><summary><code>nodes/Node_127_BambuLab/</code> — 1 条</summary>

- `nodes/Node_127_BambuLab/enhanced_bambu_controller.py`（1）：`M EnhancedBambuController.add_to_history` — · 动作/变更

</details>

<details><summary><code>nodes/Node_14_FFmpeg/</code> — 1 条</summary>

- `nodes/Node_14_FFmpeg/main.py`（1）：`M FFmpegManager.merge_videos` — · 动作/变更

</details>

<details><summary><code>nodes/Node_33_ADB/</code> — 1 条</summary>

- `nodes/Node_33_ADB/cluster_manager.py`（1）：`M ADBClusterManager.parallel_execute` — · 动作/变更

</details>

<details><summary><code>nodes/Node_50_Transformer/</code> — 1 条</summary>

- `nodes/Node_50_Transformer/enhanced_nlu_engine.py`（1）：`M EnhancedNLUEngine.generate_software_command` — · 计算/构造

</details>

<details><summary><code>nodes/Node_58_ModelRouter/</code> — 1 条</summary>

- `nodes/Node_58_ModelRouter/main.py`（1）：`M DatabaseManager.save_session_turn` T · 动作/变更

</details>

<details><summary><code>nodes/Node_74_DigitalTwin/</code> — 1 条</summary>

- `nodes/Node_74_DigitalTwin/main.py`（1）：`M TwinDeviceRegistration.to_registered_runtime_device` — · 序列化/转换

</details>

<details><summary><code>nodes/Node_89_APIGateway/</code> — 1 条</summary>

- `nodes/Node_89_APIGateway/main.py`（1）：`M GatewayService.proxy_via_route` — · 动作/变更

</details>

<!-- END GENERATED -->
