# Architecture Review — 统一主体架构 (Unified Subject Architecture)

> 本文是仓库级架构审查的入口摘要。规范性细节见
> [docs/UNIFIED_SUBJECT_ARCHITECTURE.md](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)。

## 统一主体架构

`DesktopPresenceRuntime`（运行时外壳）与 `OpenClawd`（主体认知核心）是**同一主体的两层**，
而非两个并行主体：

```
UFO Galaxy Subject
├─ DesktopPresenceRuntime  ← runtime shell：三态生命周期、runtime_session_id、桌面多模态感知
└─ OpenClawd               ← subject core：认知、决策、执行策略（PolicyGate）
```

## 规范启动与请求链路 (PR-01)

唯一主入口为 `main.py`，请求生命周期沿单一规范链路流动：

```
main.py
  → unified_launcher.py                                  (子入口, Phase 4-6)
    → DesktopPresenceRuntime.handle_request              (阶段入口: runtime shell)
      → OpenClawd.process                                (内部阶段入口: subject core)
        → CommandRouter.route_envelope                   (内部阶段入口: 跨设备分发底座)
```

入口角色登记与守卫见 `entrypoint_role_contract.py`；兼容/遗留入口
（gateway chat 适配器、legacy dashboard、`scripts/launcher_v2.py`、docker compose 包装）
均被显式标记为非主入口。

## 关键运行时层

| 层 | 模块 | 职责 |
|---|---|---|
| 拓扑真相 | `core/network_topology_runtime.py` (PR-8) | 设备/网关/NATS fabric 的规范拓扑视图 |
| 任务真相 | `core/canonical_task.py` | CanonicalTask → TaskEnvelope → route_envelope 主链 |
| 域治理 | `core/device_node_domain_governance.py` (PR-5) | 设备域与节点域职责边界 |
| L4 增强 | `core/galaxy_main_loop_l4_enhanced.py` | 后台自主认知增强循环（不在 per-request 路径上） |
