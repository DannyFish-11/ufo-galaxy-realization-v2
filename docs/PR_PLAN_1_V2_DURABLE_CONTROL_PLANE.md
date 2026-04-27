# PR-1：V2 Durable Control Plane Closure

> **目标仓库**：`DannyFish-11/ufo-galaxy-realization-v2`  
> **优先级**：最高（关闭 P0 gap `GAP_V2_TRUTH_PERSISTENCE`）  
> **核心问题**：V2 是中心式编排权威，但 session truth 和 inflight task 状态不跨重启持久化

---

## Problem Statement

V2 control plane 是这套双仓系统的 canonical truth authority 和 orchestration center。当前状态：

1. **`CanonicalSessionTruthRuntime`** 使用 in-memory `deque` ring buffer 作为主运行时，进程重启后所有 session truth 丢失
2. **`task_lifecycle_persistence.py` 的 snapshot 层已实现**，但 startup → coordinator → re-dispatch 的完整恢复调用链未接通
3. **`durable_audit_store` 已自动挂载**（startup step 19），但这是 observational attachment，不替换 ring buffer 的 truth authority 地位
4. **`GAP_V2_TRUTH_PERSISTENCE`** 在 `core/dual_repo_system_map.py` 中标记 `resolved=False`（P0）

这意味着：V2 重启后，所有进行中的任务状态（inflight）、session continuity、result dedup 记录（后者已通过 `durable_result_idempotency.py` 解决）均会失真或中断。对一个中心 authority 系统来说，这是最关键的成熟度缺口。

---

## 目标

关闭 `GAP_V2_TRUTH_PERSISTENCE`，使 V2 达到：

> **默认 durable control plane**：进程重启后，session truth 可重建，inflight task 可恢复，continuation 可重新绑定

---

## 具体工作项

### 1. Session Truth 默认持久化

**文件**：`core/canonical_session_truth.py`

当前：`CanonicalSessionTruthRuntime._store` 是 `deque`，`set_audit_store` 是可选 attach。

需要：`record_session_truth` 在写入 ring buffer 的同时，**默认**写入 durable snapshot store（而不是等 `set_audit_store` 被显式调用）。

```python
# 建议修改方向：startup wire 完成后，singleton runtime 自动有 durable store
# 不需要等待外部调用 set_audit_store
```

### 2. 完整接通 Inflight Task Recovery 调用链

**文件**：`core/runtime_restart_recovery.py`, `core/startup.py`

当前：`restore_inflight_tasks_from_snapshot` 存在，`RuntimeRestartRecoveryCoordinator` 引用了 policy sentinel，但 startup 流程中是否实际调用了 coordinator 并驱动任务重新分发，缺乏端到端的代码路径和测试。

需要：
- `RuntimeRestartRecoveryCoordinator.recover()` 在 startup 流程中被调用
- RESUMABLE 任务被重新分发到目标设备（如果设备已重连）
- REPLAY_ONLY 任务被推回 routing 层
- 有测试覆盖：startup → snapshot load → task recover → dispatch

### 3. Session Truth Snapshot 重建路径

**文件**：`core/canonical_session_truth.py`, `core/replay_audit_persistence.py`

当前：ring buffer 重启后清空。`DurableAuditStore` 里有 truth records，但没有从 store 反向重建 runtime state 的机制。

需要：在 startup 阶段，从 `DurableAuditStore` 加载最近的 session truth records 并重建 ring buffer 初始状态（至少加载最近 N 个 session 的 truth records）。

### 4. Waiter / Continuation 跨重启重绑定

**文件**：`core/task_lifecycle_persistence.py`, `core/flow_continuity_coordinator.py`

当前：continuation waiter（future 对象）是纯内存态，重启后失效。

需要：对 RESUMABLE 任务，重启后重新创建 waiter/continuation 绑定。不要求完全透明恢复，但需要：要么恢复 waiter，要么对超时任务执行 reconcile（发送 error result，清理状态）。

### 5. 将 GAP_V2_TRUTH_PERSISTENCE 标记为 resolved

**文件**：`core/dual_repo_system_map.py`

以上代码变更合并后，更新 `resolved=True` 并附 PR 引用。

---

## 验收标准

- [ ] `GAP_V2_TRUTH_PERSISTENCE` 在 `WORKSTREAM_GAP_REGISTRY` 中 `resolved=True`
- [ ] 新增测试：V2 进程模拟重启 → session truth 重建 → inflight task 恢复
- [ ] `core/startup.py` 的 startup flow 明确调用 `RuntimeRestartRecoveryCoordinator.recover()`
- [ ] `dual_repo_integration.yml` 的 `release-readiness-gate` 通过（readiness matrix 维度 `truth_recovery` pass）
- [ ] 不引入新的可绕过路径

---

## 预期影响

完成后，V2 从"强编排、弱恢复"变为"强编排、有意义的默认 durable recovery"。这是让系统跨过"准成熟系统"门槛 A 的必要条件。
